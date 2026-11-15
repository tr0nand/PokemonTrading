"""Configurable trading simulation for the Pokemon trading game.

Spins up a tracker plus N trainers on localhost, funds every trainer via
round-robin mining, then runs bot traders for a set duration while miners
are picked by weighted share. Prints a rarity tally at the end.

Usage:
    python simulator.py --trainers 20 --minutes 20
    python simulator.py --trainers 4 --miner-weights 50,25,12.5,12.5 \\
        --eagerness 3 --accept-rate 0.8 --fair-only --seed 7

Knobs:
    --trainers N        number of bot trainers
    --miner-weights     comma-separated mining shares, one per trainer
                        (e.g. "50,25,25"); default is uniform
    --eagerness R       mean trade attempts per second per bot
    --accept-rate P     probability of accepting an offer (0..1)
    --fair-only         only accept trades that don't lose rarity
"""

import argparse
import json
import random
import threading
import time

import requests

from app import create_app, register_with_tracker
from blockchain import Blockchain
from nodetracker import create_tracker
from pokedex import load_dex

SETTLE = 1.5


def parse_weights(spec, n):
    """Parse a comma-separated mining-share spec into n floats.

    Raises ValueError when the count mismatches, values aren't numeric,
    any is negative, or all are zero.
    """
    try:
        weights = [float(part) for part in spec.split(",")]
    except ValueError:
        raise ValueError(f"miner weights must be numbers: {spec!r}")
    if len(weights) != n:
        raise ValueError(f"need {n} miner weights, got {len(weights)}")
    if any(w < 0 for w in weights):
        raise ValueError("miner weights cannot be negative")
    if sum(weights) <= 0:
        raise ValueError("miner weights must sum above zero")
    return weights


def choose_miner(weights, rng):
    """Pick a trainer index by mining share."""
    return rng.choices(range(len(weights)), weights=weights, k=1)[0]


def summarize_holdings(holdings_by_trainer, dex):
    """Tally a {trainer_index: [dex numbers]} map into counts and rares."""
    by_rarity = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
    rares = []
    for owner, nats in holdings_by_trainer.items():
        for nat in nats:
            name, rarity = dex[int(nat)]
            by_rarity[rarity] += 1
            if rarity >= 4:
                rares.append(
                    {"owner": owner, "nat": int(nat), "name": name, "rarity": rarity}
                )
    rares.sort(key=lambda r: (-r["rarity"], r["name"]))
    return {"by_rarity": by_rarity, "rares": rares}


def with_retries(fn, attempts=5, delay=1.0):
    """Call fn(), retrying request failures with linear backoff."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except requests.RequestException as exc:
            last = exc
            time.sleep(delay * (i + 1))
    raise last


class Sim:
    def __init__(self, args):
        self.args = args
        self.rng = random.Random(args.seed)
        self.tracker_url = f"http://127.0.0.1:{args.tracker_port}"
        self.nodes = [
            f"http://127.0.0.1:{args.base_port + i}/node"
            for i in range(args.trainers)
        ]
        self.roots = [f"http://127.0.0.1:{args.base_port + i}" for i in range(args.trainers)]
        self.weights = (
            parse_weights(args.miner_weights, args.trainers)
            if args.miner_weights
            else [1.0] * args.trainers
        )
        self.dex = load_dex()
        self.calc = Blockchain("sim")  # local holdings math, never served
        self.stop = threading.Event()
        self.session = requests.Session()
        self.accepted = 0
        self.accepted_lock = threading.Lock()
        self.log_file = open(args.log, "w", buffering=1) if args.log else None
        # Shared chain snapshot: the dev server closes every connection, so
        # request volume (not pooling) is what must stay within localhost's
        # ephemeral-port budget. Bots share one cached view instead of each
        # fetching the full chain per trade.
        self._chain_lock = threading.Lock()
        self._chain_cached_at = 0.0
        self._chain_cached = None

    def log(self, msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        if self.log_file:
            self.log_file.write(line + "\n")

    def run_tracker(self):
        create_tracker().run(
            host="0.0.0.0", port=self.args.tracker_port, threaded=True, use_reloader=False
        )

    def run_trainer(self, i):
        app = create_app(self.nodes[i], self.tracker_url)
        threading.Thread(
            target=register_with_tracker,
            args=(self.tracker_url, self.nodes[i]),
            daemon=True,
        ).start()
        app.run(host="0.0.0.0", port=self.args.base_port + i, threaded=True, use_reloader=False)

    def verify_servers(self, timeout=60):
        """Fail fast unless every server answers with the right identity.

        Catches bind collisions (a dead thread, or a stranger holding the
        port) in seconds instead of after an hour of confusing failures.
        """
        deadline = time.time() + timeout
        while True:
            missing = []
            try:
                payload = self.session.get(
                    f"{self.tracker_url}/nodes", timeout=3
                ).json()
                tracker_ok = isinstance(payload, dict) and isinstance(
                    payload.get("nodes"), list
                )
            except (requests.RequestException, ValueError):
                tracker_ok = False
            if not tracker_ok:
                missing.append(f"tracker :{self.args.tracker_port}")
            for i in range(self.args.trainers):
                try:
                    body = self.session.get(f"{self.roots[i]}/", timeout=3).text
                    ok = 'name="user"' in body
                except requests.RequestException:
                    ok = False
                if not ok:
                    missing.append(f"trainer-{i} :{self.args.base_port + i}")
            if not missing:
                return
            if time.time() >= deadline:
                self.log(f"FATAL: servers never came up: {', '.join(missing)}")
                raise SystemExit(1)
            time.sleep(min(2, max(0, deadline - time.time())))

    def wait_ready(self):
        deadline = time.time() + 300
        while time.time() < deadline:
            try:
                nodes = self.session.get(f"{self.tracker_url}/nodes", timeout=5).json()["nodes"]
                if len(nodes) >= self.args.trainers:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            self.log("FATAL: trainers did not register in time")
            raise SystemExit(1)
        time.sleep(5)  # let introductions land
        for i in range(self.args.trainers):
            try:
                requests.post(f"{self.roots[i]}/", data={"user": f"Sim-{i}"}, timeout=5)
            except Exception as exc:
                self.log(f"username {i} failed: {exc}")
        self.log(f"ready: {self.args.trainers} trainers peered")

    def chain_of(self, i):
        return with_retries(
            lambda: self.session.get(f"{self.nodes[i]}/chain", timeout=15).json()["chain"]
        )

    def shared_chain(self):
        with self._chain_lock:
            if (
                self._chain_cached is not None
                and time.time() - self._chain_cached_at < self.args.chain_cache
            ):
                return self._chain_cached
        chain = with_retries(
            lambda: self.session.get(f"{self.nodes[0]}/chain", timeout=15).json()["chain"]
        )
        with self._chain_lock:
            self._chain_cached_at = time.time()
            self._chain_cached = chain
        return chain

    def mine(self, i, timeout):
        """Mine on trainer i, failing loudly on HTTP errors (wrong server)."""
        with_retries(lambda: self._checked_get(f"{self.roots[i]}/mine", timeout))

    def _checked_get(self, url, timeout):
        resp = self.session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp

    def phase_funding(self):
        for _ in range(self.args.funding_rounds):
            for i in range(self.args.trainers):
                self.mine(i, timeout=60)
                time.sleep(self.args.funding_settle)
        time.sleep(SETTLE)
        lengths = sorted({len(self.chain_of(i)) for i in range(self.args.trainers)})
        self.log(f"funding done, chain lengths: {lengths}")

    def bot(self, i):
        s = requests.Session()
        n = self.args.trainers
        while not self.stop.is_set():
            try:
                a, b = self.rng.sample(range(n), 2)
                chain = self.shared_chain()
                ha = self.calc.holdings(self.nodes[a], chain)
                hb = self.calc.holdings(self.nodes[b], chain)
                if not ha or not hb:
                    time.sleep(0.5)
                    continue
                x = self.rng.choice(ha)
                y = self.rng.choice(hb)
                if self.rng.random() >= self.args.accept_rate:
                    continue  # B declines before the offer goes out
                if self.args.fair_only and self.dex[y][1] > self.dex[x][1]:
                    continue  # B only takes non-losing trades
                ts = time.time()
                r = s.post(
                    f"{self.nodes[b]}/trade/off",
                    json={"node": self.nodes[a], "sent": x, "rec": y, "timestamp": ts},
                    timeout=5,
                )
                if r.status_code != 200:
                    continue
                r2 = s.post(
                    f"{self.roots[b]}/trade/resp",
                    data={
                        "submit": "Accept",
                        "node": self.nodes[a],
                        "Sendpoke": x,
                        "Rec": y,
                        "tim": ts,
                    },
                    timeout=10,
                )
                if r2.ok:
                    with self.accepted_lock:
                        self.accepted += 1
            except Exception as exc:
                self.log(f"bot{i} err {type(exc).__name__}")
            time.sleep(self.rng.uniform(0, 2 / self.args.eagerness))

    def phase_trading(self):
        bots = [
            threading.Thread(target=self.bot, args=(i,), daemon=True)
            for i in range(self.args.trainers)
        ]
        for t in bots:
            t.start()
        deadline = time.time() + self.args.minutes * 60
        rounds = 0
        last_mine = 0.0
        mined_mark = 0
        while time.time() < deadline:
            time.sleep(2)
            miner = choose_miner(self.weights, self.rng)
            with self.accepted_lock:
                unmined = self.accepted - mined_mark
            try:
                if unmined < self.args.target_pending:
                    continue
                wait = self.args.min_round_interval - (time.time() - last_mine)
                if wait > 0:
                    time.sleep(wait)
                with self.accepted_lock:
                    mined_mark = self.accepted
                self.mine(miner, timeout=90)
                last_mine = time.time()
                block = self.chain_of(miner)[-1]
                rew = int(block["rew"])
                name, rarity = self.dex[rew]
                rounds += 1
                self.log(
                    f"ROUND {rounds} miner={miner} trades={len(block['trade'])} "
                    f"reward={name}(r{rarity}) chain={block['index']}"
                )
                time.sleep(SETTLE)
            except Exception as exc:
                self.log(f"miner err {type(exc).__name__}")
                time.sleep(2)
        self.stop.set()
        for t in bots:
            t.join(timeout=10)
        return rounds

    def tally(self, rounds):
        time.sleep(SETTLE)
        chain = max((self.chain_of(i) for i in range(self.args.trainers)), key=len)
        holdings = {
            i: self.calc.holdings(self.nodes[i], chain) for i in range(self.args.trainers)
        }
        summary = summarize_holdings(holdings, self.dex)
        result = {
            "rounds": rounds,
            "chain_length": len(chain),
            "trainers": self.args.trainers,
            **summary,
        }
        with open(self.args.results, "w") as f:
            json.dump(result, f, indent=2)
        self.log(f"tally rounds={rounds} chain={len(chain)} rarity={summary['by_rarity']}")
        for r in summary["rares"]:
            self.log(f"RARE trainer={r['owner']} {r['name']} (r{r['rarity']})")
        self.log(f"results -> {self.args.results}")
        return result


def build_parser():
    parser = argparse.ArgumentParser(description="Simulate Pokemon trading activity")
    parser.add_argument("--trainers", type=int, default=20)
    parser.add_argument("--minutes", type=float, default=20)
    parser.add_argument("--miner-weights", default=None)
    parser.add_argument("--eagerness", type=float, default=2.0)
    parser.add_argument("--accept-rate", type=float, default=1.0)
    parser.add_argument("--fair-only", action="store_true")
    parser.add_argument("--target-pending", type=int, default=24)
    parser.add_argument("--funding-rounds", type=int, default=3)
    parser.add_argument("--tracker-port", type=int, default=5109)
    parser.add_argument("--base-port", type=int, default=5110)
    parser.add_argument("--startup-stagger", type=float, default=1.0)
    parser.add_argument("--funding-settle", type=float, default=1.0)
    parser.add_argument("--chain-cache", type=float, default=10.0)
    parser.add_argument("--min-round-interval", type=float, default=15.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--results", default="sim_results.json")
    parser.add_argument("--log", default=None)
    parser.add_argument("--serve-after", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.trainers < 2:
        parser.error("--trainers must be at least 2")
    if args.minutes <= 0:
        parser.error("--minutes must be positive")
    if args.eagerness <= 0:
        parser.error("--eagerness must be positive")
    if not 0 <= args.accept_rate <= 1:
        parser.error("--accept-rate must be between 0 and 1")
    if args.target_pending < 1:
        parser.error("--target-pending must be at least 1")
    if args.funding_rounds < 1:
        parser.error("--funding-rounds must be at least 1")
    if args.startup_stagger < 0:
        parser.error("--startup-stagger cannot be negative")
    if args.funding_settle < 0:
        parser.error("--funding-settle cannot be negative")
    if args.chain_cache < 0:
        parser.error("--chain-cache cannot be negative")
    if args.min_round_interval < 0:
        parser.error("--min-round-interval cannot be negative")
    try:
        sim = Sim(args)
    except ValueError as exc:
        parser.error(str(exc))
    threading.Thread(target=sim.run_tracker, daemon=True).start()
    time.sleep(1)  # tracker first, then staggered trainers
    for i in range(args.trainers):
        threading.Thread(target=sim.run_trainer, args=(i,), daemon=True).start()
        time.sleep(args.startup_stagger)
    sim.verify_servers()
    sim.wait_ready()
    sim.phase_funding()
    rounds = sim.phase_trading()
    sim.tally(rounds)
    if args.serve_after:
        sim.log(f"browsing: http://127.0.0.1:{args.base_port} (Ctrl-C stops)")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()

