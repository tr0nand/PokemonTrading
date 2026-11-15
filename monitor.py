"""Live dashboard for watching trainers' collections.

Points at a tracker (auto-discovers trainers) or an explicit trainer list,
fetches one status snapshot per trainer plus the longest chain once, and
renders every trainer's current Pokemon. The page auto-refreshes.

Usage:
    python monitor.py --tracker http://127.0.0.1:5109 --port 5200
    python monitor.py --trainers http://127.0.0.1:5010/node,http://127.0.0.1:5011/node

Then open http://127.0.0.1:5200 in a browser.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

import requests
from flask import Flask, render_template

from blockchain import Blockchain
from pokedex import load_dex

INFO_TIMEOUT = 3
CHAIN_TIMEOUT = 15
WORKERS = 20


def _get_json(url, timeout):
    try:
        return requests.get(url, timeout=timeout).json()
    except (requests.RequestException, ValueError):
        return None


def discover_trainers(tracker_url, explicit):
    """Trainer node URLs from an explicit list or tracker discovery."""
    if explicit:
        return list(dict.fromkeys(u for u in explicit if u))
    if not tracker_url:
        return []
    payload = _get_json(f"{tracker_url}/nodes", INFO_TIMEOUT)
    nodes = payload.get("nodes") if isinstance(payload, dict) else None
    if not isinstance(nodes, list):
        return []
    return sorted(n for n in nodes if isinstance(n, str) and n)


def _unc_url(node_url):
    base = node_url[: -len("/node")] if node_url.endswith("/node") else node_url
    return f"{base}/trade/unc"


def fetch_infos(trainers):
    """Map each trainer URL to its /node/info payload (None if unreachable).

    Trainers predating /node/info fall back to their pending queue: that
    still proves reachability and yields a live pending count.
    """

    def one(url):
        payload = _get_json(f"{url}/info", INFO_TIMEOUT)
        if isinstance(payload, dict):
            return url, payload
        unc = _get_json(_unc_url(url), INFO_TIMEOUT)
        if not isinstance(unc, list):
            return url, None
        return url, {"node": url, "user": "", "length": None, "pending": len(unc)}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return dict(pool.map(one, trainers))


def label(node_url, user):
    try:
        port = urlparse(node_url).port or "?"
    except ValueError:
        port = "?"
    name = (user or "").strip() or "Trainer"
    return f"{name} :{port}"


def fetch_longest_chain(urls, infos):
    """Longest chain across trainers (first reachable as fallback)."""
    best, best_len = None, -1
    for url in urls:
        length = (infos.get(url) or {}).get("length")
        if isinstance(length, int) and length > best_len:
            best, best_len = url, length
    if best is None:
        best = next((u for u in urls if infos.get(u) is not None), None)
    if best is None:
        return []
    payload = _get_json(f"{best}/chain", CHAIN_TIMEOUT)
    if isinstance(payload, dict) and isinstance(payload.get("chain"), list):
        return payload["chain"]
    return []


def _tlabel(labels, value):
    if value is None:
        return "?"
    if isinstance(value, str):
        return labels.get(value, value)
    return str(value)


def _mon(dex, nat):
    try:
        nat = int(nat)
        name, rarity = dex[nat]
        return {"nat": nat, "name": name, "rarity": rarity}
    except (KeyError, TypeError, ValueError):
        return {"nat": None, "name": "?", "rarity": 0}


def _short(value):
    return str(value)[:16] if value is not None else "?"


def _fmt_time(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return "?"


def format_block(block, labels, dex):
    """Render-ready block dict, or None for non-dict entries."""
    if not isinstance(block, dict):
        return None
    trades = []
    raw = block.get("trade") if isinstance(block.get("trade"), list) else []
    for t in raw:
        if not isinstance(t, dict):
            continue
        try:
            t1, t2 = t["trainer1"], t["trainer2"]
            s1, s2 = int(t["sentby1"]), int(t["sentby2"])
        except (KeyError, TypeError, ValueError):
            continue
        trades.append(
            {
                "trainer1": _tlabel(labels, t1),
                "trainer2": _tlabel(labels, t2),
                "sent1": _mon(dex, s1),
                "sent2": _mon(dex, s2),
            }
        )
    try:
        block_hash = _short(Blockchain.hash(block))
    except (TypeError, ValueError):
        block_hash = "?"
    return {
        "index": block.get("index", "?"),
        "time": _fmt_time(block.get("timestamp")),
        "miner": _tlabel(labels, block.get("miner")),
        "trades": trades,
        "trade_count": len(trades),
        "reward": _mon(dex, block.get("rew")),
        "proof": block.get("proof", "?"),
        "prev": _short(block.get("previous_hash")),
        "hash": block_hash,
    }


def build_chain_view(tracker_url, trainers, dex):
    """Newest-first render-ready blocks."""
    urls = discover_trainers(tracker_url, trainers)
    infos = fetch_infos(urls)
    chain = fetch_longest_chain(urls, infos)
    labels = {u: label(u, (infos.get(u) or {}).get("user", "")) for u in urls}
    blocks = []
    for block in reversed(chain):
        formatted = format_block(block, labels, dex)
        if formatted is not None:
            blocks.append(formatted)
    return {"blocks": blocks, "count": len(chain)}


def build_dashboard(tracker_url, trainers, dex, calc):
    """Snapshot the network into render-ready trainer cards."""
    urls = discover_trainers(tracker_url, trainers)
    infos = fetch_infos(urls)
    chain = fetch_longest_chain(urls, infos)
    cards = []
    for url in urls:
        info = infos.get(url)
        mons = []
        if chain:
            try:
                owned = calc.holdings(url, chain)
            except Exception:
                owned = []
            for nat in sorted(owned):
                try:
                    name, rarity = dex[int(nat)]
                except (KeyError, TypeError, ValueError):
                    continue
                mons.append(
                    {
                        "nat": int(nat),
                        "name": name,
                        "rarity": rarity,
                        "img": f"{int(nat)}.png",
                    }
                )
        info = info or {}
        counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for m in mons:
            counts[m["rarity"]] += 1
        cards.append(
            {
                "label": label(url, info.get("user", "")),
                "url": url,
                "reachable": infos.get(url) is not None,
                "length": info.get("length"),
                "pending": info.get("pending"),
                "mons": mons,
                "counts": counts,
                "rares": [m for m in mons if m["rarity"] >= 4],
            }
        )
    cards.sort(key=lambda t: (-len(t["rares"]), -len(t["mons"]), t["label"]))
    max_rarity = 0
    for t in cards:
        for m in t["mons"]:
            max_rarity = max(max_rarity, m["rarity"])
    top_rares = []
    if max_rarity >= 4:
        top_rares = [
            {
                "trainer": t["label"],
                "nat": m["nat"],
                "name": m["name"],
                "rarity": m["rarity"],
            }
            for t in cards
            for m in t["mons"]
            if m["rarity"] == max_rarity
        ]
        top_rares.sort(key=lambda r: r["name"])
    return {
        "trainers": cards,
        "count": len(urls),
        "chain_length": len(chain),
        "total_mons": sum(len(t["mons"]) for t in cards),
        "max_rarity": max_rarity,
        "top_rares": top_rares,
    }


def create_monitor(tracker_url=None, trainers=(), refresh=15):
    """Build the monitor Flask app. Testable without live trainers."""
    app = Flask(__name__, template_folder="templates")
    dex = load_dex()
    calc = Blockchain("monitor")

    @app.route("/")
    def dashboard():
        data = build_dashboard(tracker_url, trainers, dex, calc)
        return render_template("monitor.html", refresh=refresh, **data)

    @app.route("/chain")
    def chain_view():
        data = build_chain_view(tracker_url, trainers, dex)
        return render_template("chain.html", refresh=refresh, **data)

    return app


def build_parser():
    parser = argparse.ArgumentParser(description="Watch trainers' collections live")
    parser.add_argument("--tracker", default=None, help="tracker base URL")
    parser.add_argument("--trainers", default=None, help="comma-separated node URLs")
    # 5300 sits clear of the simulator's default range (5109-5209+).
    parser.add_argument("--port", type=int, default=5300)
    parser.add_argument("--refresh", type=int, default=15)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    explicit = [u.strip() for u in args.trainers.split(",")] if args.trainers else []
    if not args.tracker and not explicit:
        parser.error("need --tracker or --trainers")
    if args.refresh < 1:
        parser.error("--refresh must be at least 1")
    create_monitor(args.tracker, explicit, args.refresh).run(
        host="0.0.0.0", port=args.port, threaded=True
    )


if __name__ == "__main__":
    main()
