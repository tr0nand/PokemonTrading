"""Trainer registry (tracker) for the Pokemon trading game.

Fresh rewrite of the original nodetracker.py. Trainers register here on
startup; the tracker introduces each newcomer to the trainers it already
knows so they can peer directly and sync chains.

Wire protocol (all JSON):
  POST /nodes  {"node": "<trainer base url>"}   register (idempotent)
  GET  /nodes                               list registered trainers
Introductions are POSTed to the trainer's own base url as
  {"node": "<peer url>", "fetch_chain": <bool>}
where fetch_chain tells a newcomer to pull the chain from an established
peer, while established peers just record the newcomer.
"""

import argparse
import threading

import requests
from flask import Flask, jsonify, request
from requests.adapters import HTTPAdapter

INTRO_TIMEOUT = 5

# Shared keep-alive session: registering N trainers fires ~2N introductions,
# which exhausts localhost ephemeral ports without connection reuse.
_SESSION = requests.Session()
_SESSION.mount("http://", HTTPAdapter(pool_connections=128, pool_maxsize=8))
_SESSION.mount("https://", HTTPAdapter(pool_connections=128, pool_maxsize=8))


def announce(url, payload):
    """Best-effort POST of an introduction payload. Returns True on 2xx."""
    try:
        resp = _SESSION.post(url, json=payload, timeout=INTRO_TIMEOUT)
        return 200 <= resp.status_code < 300
    except requests.RequestException:
        return False


def create_tracker():
    """Build the tracker Flask app. Testable without a live server."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    nodes = set()
    lock = threading.Lock()

    @app.route("/nodes", methods=["GET"])
    def list_nodes():
        with lock:
            return jsonify({"nodes": sorted(nodes)}), 200

    @app.route("/nodes", methods=["POST"])
    def register_node():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("node"), str):
            return jsonify({"error": "expected JSON {'node': url}"}), 400
        node = data["node"].strip()
        if not node.startswith(("http://", "https://")):
            return jsonify({"error": "node must be an http(s) URL"}), 400
        with lock:
            if node in nodes:
                return jsonify({"status": "already known", "node": node}), 200
            peers = sorted(nodes)
            nodes.add(node)
        for peer in peers:
            announce(peer, {"node": node, "fetch_chain": False})
            announce(node, {"node": peer, "fetch_chain": True})
        return (
            jsonify({"status": "registered", "node": node, "peers": peers}),
            200,
        )

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pokemon trading tracker")
    parser.add_argument("port", type=int, help="port to listen on")
    args = parser.parse_args(argv)
    create_tracker().run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
