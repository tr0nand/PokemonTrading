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


def fetch_infos(trainers):
    """Map each trainer URL to its /node/info payload (None if unreachable)."""

    def one(url):
        payload = _get_json(f"{url}/info", INFO_TIMEOUT)
        return url, payload if isinstance(payload, dict) else None

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return dict(pool.map(one, trainers))


def label(node_url, user):
    try:
        port = urlparse(node_url).port or "?"
    except ValueError:
        port = "?"
    name = (user or "").strip() or "Trainer"
    return f"{name} :{port}"


def build_dashboard(tracker_url, trainers, dex, calc):
    """Snapshot the network into render-ready trainer cards."""
    urls = discover_trainers(tracker_url, trainers)
    infos = fetch_infos(urls)
    best, best_len = None, -1
    for url in urls:
        length = (infos.get(url) or {}).get("length")
        if isinstance(length, int) and length > best_len:
            best, best_len = url, length
    chain = []
    if best is not None:
        payload = _get_json(f"{best}/chain", CHAIN_TIMEOUT)
        if isinstance(payload, dict) and isinstance(payload.get("chain"), list):
            chain = payload["chain"]
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
        cards.append(
            {
                "label": label(url, info.get("user", "")),
                "url": url,
                "reachable": infos.get(url) is not None,
                "length": info.get("length"),
                "pending": info.get("pending"),
                "mons": mons,
                "rares": [m for m in mons if m["rarity"] >= 4],
            }
        )
    return {"trainers": cards, "count": len(urls), "chain_length": len(chain)}


def create_monitor(tracker_url=None, trainers=(), refresh=15):
    """Build the monitor Flask app. Testable without live trainers."""
    app = Flask(__name__, template_folder="templates")
    dex = load_dex()
    calc = Blockchain("monitor")

    @app.route("/")
    def dashboard():
        data = build_dashboard(tracker_url, trainers, dex, calc)
        return render_template("monitor.html", refresh=refresh, **data)

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
