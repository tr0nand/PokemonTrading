"""Trainer node: personal chain, trading, and web UI.

Fresh rewrite of the original app.py. Each trainer runs one of these
processes: it registers with the tracker, mines blocks for Pokemon
rewards, and trades with other trainers peer-to-peer.

Routes starting with /node/ are the peer API (JSON); the rest are the
browser UI. Template contexts match templates/ so the existing pages
render unchanged.
"""

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for

from blockchain import Blockchain
from pokedex import pokemon_name

POST_TIMEOUT = 5
GET_TIMEOUT = 10
PULL_TIMEOUT = 3
PULL_WORKERS = 20

STATUS_NO_RESPONSE = "No response yet"
STATUS_ACCEPTED = "Accepted but Unverified"
STATUS_VERIFIED = "Verified"
STATUS_CANCELLED = "Cancelled"
STATUS_INVALID = "Invalid"
REMOTE_STATUSES = {STATUS_ACCEPTED, STATUS_CANCELLED, STATUS_INVALID}


def _post_json(url, payload, timeout=POST_TIMEOUT):
    """Best-effort JSON POST. Returns the response or None."""
    try:
        return requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException:
        return None


def _get_json(url, timeout=GET_TIMEOUT):
    """Best-effort JSON GET. Returns the decoded body or None."""
    try:
        return requests.get(url, timeout=timeout).json()
    except (requests.RequestException, ValueError):
        return None


def _card(dex, nat, trainer=None):
    card = {"name": pokemon_name(dex, nat), "id": f"{nat}.png", "num": nat}
    if trainer is not None:
        card["trainer"] = trainer
    return card


def _mark_invalid_local(blockchain, trade):
    """Mark our own outgoing request invalid. Lock-protected, no I/O."""
    with blockchain.lock:
        for req in blockchain.tradereqs:
            if str(req.get("node")) == str(trade.get("trainer2")) and str(
                req.get("timestamp")
            ) == str(trade.get("time")):
                req["status"] = STATUS_INVALID
                break


def _notify_invalid_remote(trade):
    """Tell the requesting trainer their trade was invalid. Network I/O:
    call without holding the chain lock."""
    _post_json(
        f"{trade.get('trainer1')}/trade/offerresp",
        {
            "node": trade.get("trainer2"),
            "tim": trade.get("time"),
            "status": STATUS_INVALID,
        },
    )


def _peer_unc_url(node_url):
    base = node_url[: -len("/node")] if node_url.endswith("/node") else node_url
    return f"{base}/trade/unc"


def _pull_mempool(blockchain, peers):
    """Merge peers' pending trades into our queue (deduplicated).

    Pulling at mine time replaces broadcast-on-accept: one small fan-out per
    block instead of one per trade, which is what lets large networks breathe.
    """
    with ThreadPoolExecutor(max_workers=PULL_WORKERS) as pool:
        results = list(
            pool.map(lambda p: _get_json(_peer_unc_url(p), PULL_TIMEOUT), peers)
        )
    with blockchain.lock:
        seen = {blockchain._trade_key(t) for t in blockchain.current_trade}
        for trades in results:
            if not isinstance(trades, list):
                continue
            for trade in trades:
                if not isinstance(trade, dict):
                    continue
                try:
                    key = blockchain._trade_key(trade)
                    if key in seen:
                        continue
                    blockchain.new_transaction(
                        trade["trainer1"],
                        trade["trainer2"],
                        trade["sentby1"],
                        trade["sentby2"],
                        trade["time"],
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                seen.add(key)


def _refresh_outgoing_statuses(blockchain):
    """Promote accepted requests to verified once their trade is on chain."""
    with blockchain.lock:
        for req in blockchain.tradereqs:
            if req.get("status") != STATUS_ACCEPTED:
                continue
            for block in blockchain.chain:
                for trade in block.get("trade", []):
                    if trade.get("trainer1") == blockchain.node and str(
                        req.get("timestamp")
                    ) == str(trade.get("time")):
                        req["status"] = STATUS_VERIFIED
                        break


def register_with_tracker(tracker_url, node_url, attempts=5, delay=1.0):
    """Register this trainer with the tracker, retrying if it is not up yet."""
    for _ in range(attempts):
        resp = _post_json(f"{tracker_url}/nodes", {"node": node_url})
        if resp is not None and resp.ok:
            return True
        time.sleep(delay)
    return False


def create_app(node_url, tracker_url=None):
    """Build the trainer Flask app. Testable without network or processes."""
    app = Flask(__name__, template_folder="templates")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    blockchain = Blockchain(node_url)
    app.blockchain = blockchain
    app.config["TRACKER_URL"] = tracker_url

    @app.route("/", methods=["GET", "POST"])
    def start():
        if blockchain.user:
            return redirect(url_for("home"))
        if request.method == "POST":
            username = (request.form.get("user") or "").strip()
            if not username:
                return render_template("home.html")
            blockchain.user = username
            return redirect(url_for("home"))
        return render_template("home.html")

    @app.route("/home")
    def home():
        if not blockchain.user:
            return redirect(url_for("start"))
        with blockchain.lock:
            pokes = [
                {"name": pokemon_name(blockchain.dex, n), "id": f"{n}.png"}
                for n in blockchain.own_pokes()
            ]
            length = len(blockchain.chain)
            pending = len(blockchain.current_trade)
            user = blockchain.user
        return render_template(
            "main.html", name=user, pokes=pokes, chain_length=length, pending=pending
        )

    @app.route("/node", methods=["POST"])
    def register_node():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("node"), str):
            return jsonify({"error": "expected JSON {'node': url}"}), 400
        peer = data["node"]
        blockchain.nodereg(peer)
        if data.get("fetch_chain"):
            payload = _get_json(f"{peer}/chain")
            chain = payload.get("chain") if isinstance(payload, dict) else None
            if isinstance(chain, list):
                blockchain.replace_chain(chain)
        return jsonify({"status": "registered"}), 200

    @app.route("/node/chain", methods=["GET"])
    def full_chain():
        with blockchain.lock:
            return (
                jsonify({"chain": blockchain.chain, "length": len(blockchain.chain)}),
                200,
            )

    @app.route("/mine", methods=["GET"])
    def mine():
        with blockchain.lock:
            peers = sorted(blockchain.nodes)
        _pull_mempool(blockchain, peers)
        with blockchain.lock:
            valid, invalid = blockchain.filter_valid_trades()
            blockchain.current_trade = valid
            remote_invalid = []
            for trade in invalid:
                if trade.get("trainer1") == blockchain.node:
                    _mark_invalid_local(blockchain, trade)
                else:
                    remote_invalid.append(trade)
            last = blockchain.last_block
            proof = blockchain.proof_of_work(last["proof"])
            blockchain.new_block(proof, blockchain.hash(last))
            payload = {"chain": blockchain.chain, "length": len(blockchain.chain)}
            peers = sorted(blockchain.nodes)
        for trade in remote_invalid:
            _notify_invalid_remote(trade)
        for peer in peers:
            _post_json(f"{peer}/sync", payload)
        return redirect(url_for("home"))

    @app.route("/node/sync", methods=["POST"])
    def sync():
        data = request.get_json(silent=True)
        chain = data.get("chain") if isinstance(data, dict) else None
        if not isinstance(chain, list):
            return jsonify({"error": "expected JSON {'chain': [...]}}"}), 400
        adopted = blockchain.replace_chain(chain)
        return jsonify({"status": "adopted" if adopted else "kept"}), 200

    @app.route("/trade", methods=["GET"])
    def starttrade():
        pokes = [_card(blockchain.dex, n) for n in blockchain.own_pokes()]
        return render_template("trade.html", name=blockchain.user, pokes=pokes)

    @app.route("/trade/<int:param>", methods=["GET"])
    def choosetrain(param):
        if param not in blockchain.own_pokes():
            return redirect(url_for("starttrade"))
        dex = blockchain.dex
        with blockchain.lock:
            peers = sorted(blockchain.nodes)
        response = []
        for peer in peers:
            for nat in blockchain.other_pokes(peer):
                response.append(_card(dex, nat, trainer=peer))
        return render_template(
            "tradereq.html",
            name=pokemon_name(dex, param),
            id=f"{param}.png",
            pokes=response,
            cur=param,
        )

    @app.route("/trade/outg", methods=["GET", "POST"])
    def tradereq():
        if request.method == "POST":
            try:
                send_nat = int(request.form.get("Sendpoke", ""))
                rec_nat = int(request.form.get("Rec", ""))
            except (TypeError, ValueError):
                return redirect(url_for("starttrade"))
            peer = request.form.get("node", "")
            if (
                not peer
                or peer == blockchain.node
                or send_nat not in blockchain.dex
                or rec_nat not in blockchain.dex
                or send_nat not in blockchain.own_pokes()
            ):
                return redirect(url_for("starttrade"))
            timestamp = time.time()
            with blockchain.lock:
                blockchain.tradereqs.append(
                    {
                        "node": peer,
                        "sent": send_nat,
                        "rec": rec_nat,
                        "status": STATUS_NO_RESPONSE,
                        "timestamp": timestamp,
                    }
                )
            _post_json(
                f"{peer}/trade/off",
                {
                    "node": blockchain.node,
                    "sent": send_nat,
                    "rec": rec_nat,
                    "timestamp": timestamp,
                },
            )
            return redirect(url_for("tradereq"))
        _refresh_outgoing_statuses(blockchain)
        with blockchain.lock:
            treqs = list(blockchain.tradereqs)
        pokes = [
            {
                "rec": pokemon_name(blockchain.dex, p["rec"]),
                "sent": pokemon_name(blockchain.dex, p["sent"]),
                "node": p["node"],
                "status": p["status"],
            }
            for p in treqs
        ]
        return render_template("tradessent.html", pokes=pokes)

    @app.route("/trade/off", methods=["GET"])
    def tradeoff():
        with blockchain.lock:
            offers = list(blockchain.offers)
        pokes = [
            {
                "sent": pokemon_name(blockchain.dex, p["sent"]),
                "rec": pokemon_name(blockchain.dex, p["rec"]),
                "node": p["node"],
                "time": p["timestamp"],
                "sentid": p["sent"],
                "recid": p["rec"],
            }
            for p in offers
        ]
        return render_template("tradeoffers.html", pokes=pokes)

    @app.route("/node/trade/off", methods=["POST"])
    def tradeoffrec():
        data = request.get_json(silent=True)
        try:
            peer = data["node"]
            send_nat = int(data["sent"])
            rec_nat = int(data["rec"])
            timestamp = data["timestamp"]
        except (TypeError, KeyError, ValueError):
            return jsonify({"error": "expected an offer object"}), 400
        if (
            not isinstance(peer, str)
            or not peer
            or timestamp is None
            or send_nat not in blockchain.dex
            or rec_nat not in blockchain.dex
        ):
            return jsonify({"error": "expected an offer object"}), 400
        with blockchain.lock:
            for offer in blockchain.offers:
                if str(offer.get("node")) == peer and str(
                    offer.get("timestamp")
                ) == str(timestamp):
                    break
            else:
                blockchain.offers.append(
                    {
                        "node": peer,
                        "sent": send_nat,
                        "rec": rec_nat,
                        "timestamp": timestamp,
                    }
                )
        return jsonify({"status": "received"}), 200

    @app.route("/trade/unc", methods=["GET"])
    def returnv():
        with blockchain.lock:
            return jsonify(list(blockchain.current_trade)), 200

    @app.route("/node/trade", methods=["POST"])
    def add_transaction():
        data = request.get_json(silent=True)
        try:
            blockchain.new_transaction(
                data["trainer1"],
                data["trainer2"],
                data["sentby1"],
                data["sentby2"],
                data["time"],
            )
        except (TypeError, KeyError, ValueError):
            return jsonify({"error": "expected a trade object"}), 400
        return jsonify({"status": "queued"}), 200

    @app.route("/trade/resp", methods=["POST"])
    def traderesponse():
        node = request.form.get("node", "")
        tim = request.form.get("tim", "")
        with blockchain.lock:
            offer = None
            for cand in blockchain.offers:
                if (
                    str(cand.get("node")) == node
                    and str(cand.get("sent")) == request.form.get("Sendpoke", "")
                    and str(cand.get("rec")) == request.form.get("Rec", "")
                    and str(cand.get("timestamp")) == tim
                ):
                    offer = cand
                    break
            if offer is not None:
                blockchain.offers.remove(offer)
        if offer is None:
            return redirect(url_for("tradeoff"))
        accepted = request.form.get("submit") == "Accept"
        if accepted:
            # No ownership recheck here: our chain view may lag the miner's,
            # whose view is the arbiter when the trade is validated. Queuing
            # only fails on malformed offers, in which case we cancel so the
            # requester is not left hanging at accepted-but-unverified.
            try:
                blockchain.new_transaction(
                    node, blockchain.node, offer["sent"], offer["rec"], tim
                )
            except ValueError:
                accepted = False
        # No broadcast here: whoever mines next pulls pending trades from
        # every peer (see _pull_mempool). One fan-out per block instead of
        # one per trade.
        if accepted:
            _post_json(
                f"{node}/trade/offerresp",
                {"node": blockchain.node, "tim": tim, "status": STATUS_ACCEPTED},
            )
        else:
            _post_json(
                f"{node}/trade/offerresp",
                {"node": blockchain.node, "tim": tim, "status": STATUS_CANCELLED},
            )
        return redirect(url_for("tradeoff"))

    @app.route("/node/trade/offerresp", methods=["POST"])
    def offresp():
        data = request.get_json(silent=True)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("node"), str)
            or data.get("tim") is None
            or data.get("status") not in REMOTE_STATUSES
        ):
            return jsonify({"error": "expected an offer response"}), 400
        with blockchain.lock:
            for req in blockchain.tradereqs:
                if str(req.get("node")) == data["node"] and str(
                    req.get("timestamp")
                ) == str(data["tim"]):
                    req["status"] = data["status"]
                    break
        return jsonify({"status": "received"}), 200

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pokemon trading trainer node")
    parser.add_argument("tracker_port", type=int, help="tracker port")
    parser.add_argument("trainer_port", type=int, help="this trainer's port")
    args = parser.parse_args(argv)
    node_url = f"http://127.0.0.1:{args.trainer_port}/node"
    tracker_url = f"http://127.0.0.1:{args.tracker_port}"
    app = create_app(node_url, tracker_url)
    thread = threading.Thread(
        target=register_with_tracker, args=(tracker_url, node_url), daemon=True
    )
    thread.start()
    app.run(host="0.0.0.0", port=args.trainer_port, threaded=True)


if __name__ == "__main__":
    main()
