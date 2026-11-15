import copy
from collections import Counter
from types import SimpleNamespace

import pytest

import app as trainer_app
from app import create_app, register_with_tracker
from pokedex import load_dex, pokemon_name

A_URL = "http://127.0.0.1:5001/node"
B_URL = "http://127.0.0.1:5002/node"


@pytest.fixture(scope="module")
def dex():
    return load_dex()


@pytest.fixture()
def posts(monkeypatch):
    calls = []

    def fake(url, payload, timeout=5):
        calls.append((url, payload))
        return None

    monkeypatch.setattr(trainer_app, "_post_json", fake)
    return calls


def make_pair():
    app_a = create_app(A_URL)
    app_b = create_app(B_URL)
    return app_a, app_a.test_client(), app_b, app_b.test_client()


def set_user(client, name="Ash"):
    return client.post("/", data={"user": name})


def mine(application):
    bc = application.blockchain
    last = bc.last_block
    return bc.new_block(bc.proof_of_work(last["proof"]), bc.hash(last))


def mine_as(application, trainer):
    bc = application.blockchain
    old, bc.node = bc.node, trainer
    try:
        return mine(application)
    finally:
        bc.node = old


def peer(client, url):
    return client.post("/node", json={"node": url})


def test_start_requires_a_name():
    client = create_app(A_URL).test_client()
    assert b"Enter name" in client.get("/").data
    assert b"Enter name" in client.post("/", data={"user": "   "}).data
    resp = set_user(client, "Ash")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/home"
    assert client.get("/").status_code == 302


def test_home_shows_collection(dex):
    application = create_app(A_URL)
    client = application.test_client()
    assert client.get("/home").status_code == 302  # no name yet
    set_user(client, "Ash")
    page = client.get("/home").data.decode()
    assert "Ash" in page
    genesis_mon = application.blockchain.own_pokes()[0]
    assert pokemon_name(dex, genesis_mon) in page


def test_mine_appends_block_and_broadcasts(posts):
    application = create_app(A_URL)
    client = application.test_client()
    peer(client, B_URL)
    resp = client.get("/mine")
    assert resp.status_code == 302
    assert len(application.blockchain.chain) == 2
    assert (f"{B_URL}/sync", {"chain": application.blockchain.chain, "length": 2}) in [
        (url, {"chain": payload["chain"], "length": payload["length"]})
        for url, payload in posts
    ]


def test_mine_drops_trade_for_unowned_mon():
    application = create_app(A_URL)
    client = application.test_client()
    owned = set(application.blockchain.own_pokes())
    stray1 = next(n for n in range(1, 152) if n not in owned)
    stray2 = next(n for n in range(1, 152) if n not in owned and n != stray1)
    resp = client.post(
        "/node/trade",
        json={
            "trainer1": A_URL,
            "trainer2": B_URL,
            "sentby1": stray1,
            "sentby2": stray2,
            "time": 1.0,
        },
    )
    assert resp.status_code == 200
    client.get("/mine")
    assert application.blockchain.last_block["trade"] == []
    assert application.blockchain.current_trade == []


def test_mine_marks_own_invalid_request():
    application = create_app(A_URL)
    client = application.test_client()
    bc = application.blockchain
    bc.tradereqs.append(
        {
            "node": B_URL,
            "sent": 10,
            "rec": 11,
            "status": "No response yet",
            "timestamp": 7.0,
        }
    )
    bc.new_transaction(A_URL, B_URL, 10, 11, 7.0)
    client.get("/mine")
    assert bc.tradereqs[0]["status"] == "Invalid"


def test_mine_notifies_remote_requester_of_invalid(posts):
    application = create_app(A_URL)
    client = application.test_client()
    bc = application.blockchain
    own = bc.own_pokes()[0]
    bc.new_transaction(B_URL, A_URL, 10, own, 9.0)
    client.get("/mine")
    assert (f"{B_URL}/trade/offerresp", {"node": A_URL, "tim": 9.0, "status": "Invalid"}) in posts


def test_full_trade_flow(posts, dex):
    app_a, ca, app_b, cb = make_pair()
    set_user(ca, "Ash")
    set_user(cb, "Misty")
    peer(ca, B_URL)
    peer(cb, A_URL)
    # Fund both sides on A's chain (the chain that will mine the trade).
    mine_as(app_a, A_URL)
    mine_as(app_a, B_URL)
    a_mon = app_a.blockchain.own_pokes()[0]
    b_mon = app_a.blockchain.other_pokes(B_URL)[0]

    # Ash offers a_mon for Msity's b_mon.
    resp = ca.post(
        "/trade/outg",
        data={"node": B_URL, "Sendpoke": a_mon, "Rec": b_mon},
    )
    assert resp.status_code == 302
    offer = next(p for u, p in posts if u == f"{B_URL}/trade/off")
    assert offer == {
        "node": A_URL,
        "sent": a_mon,
        "rec": b_mon,
        "timestamp": offer["timestamp"],
    }
    # Offer lands on Misty's node and renders.
    assert cb.post("/node/trade/off", json=offer).status_code == 200
    page = cb.get("/trade/off").data.decode()
    assert pokemon_name(dex, a_mon) in page
    assert pokemon_name(dex, b_mon) in page

    # Misty accepts: Ash is notified and the trade is broadcast.
    posts.clear()
    resp = cb.post(
        "/trade/resp",
        data={
            "submit": "Accept",
            "node": A_URL,
            "Sendpoke": a_mon,
            "Rec": b_mon,
            "tim": offer["timestamp"],
        },
    )
    assert resp.status_code == 302
    assert app_b.blockchain.offers == []
    resp_payload = next(p for u, p in posts if u == f"{A_URL}/trade/offerresp")
    assert resp_payload["status"] == "Accepted but Unverified"
    tx = next(p for u, p in posts if u == f"{A_URL}/trade")
    assert tx["trainer1"] == A_URL and tx["trainer2"] == B_URL

    # Ash receives both, mines, and the request shows verified.
    assert ca.post("/node/trade/offerresp", json=resp_payload).status_code == 200
    assert ca.post("/node/trade", json=tx).status_code == 200
    before = Counter(app_a.blockchain.own_pokes())
    ca.get("/mine")
    assert len(app_a.blockchain.last_block["trade"]) == 1
    reward = app_a.blockchain.last_block["rew"]
    assert Counter(app_a.blockchain.own_pokes()) == before - Counter(
        [a_mon]
    ) + Counter([b_mon, reward])
    assert "Verified" in ca.get("/trade/outg").data.decode()


def test_decline_marks_cancelled(posts):
    _, _, app_b, cb = make_pair()
    offer = {"node": A_URL, "sent": 10, "rec": 11, "timestamp": 3.0}
    cb.post("/node/trade/off", json=offer)
    resp = cb.post(
        "/trade/resp",
        data={
            "submit": "Reject",
            "node": A_URL,
            "Sendpoke": 10,
            "Rec": 11,
            "tim": 3.0,
        },
    )
    assert resp.status_code == 302
    assert app_b.blockchain.offers == []
    assert (f"{A_URL}/trade/offerresp", {"node": B_URL, "tim": "3.0", "status": "Cancelled"}) in posts
    assert app_b.blockchain.current_trade == []


def test_accept_unknown_offer_is_noop(posts):
    _, _, app_b, cb = make_pair()
    resp = cb.post(
        "/trade/resp",
        data={"submit": "Accept", "node": A_URL, "Sendpoke": 10, "Rec": 11, "tim": 3.0},
    )
    assert resp.status_code == 302
    assert posts == []
    assert app_b.blockchain.current_trade == []


def test_outgoing_offer_validates_holdings(posts):
    application = create_app(A_URL)
    client = application.test_client()
    own = application.blockchain.own_pokes()[0]
    stray = next(n for n in range(1, 152) if n != own)
    # Offering a mon we do not own is refused.
    resp = client.post("/trade/outg", data={"node": B_URL, "Sendpoke": stray, "Rec": 10})
    assert resp.status_code == 302
    assert application.blockchain.tradereqs == []
    assert posts == []
    # Offering to ourselves is refused too.
    resp = client.post(
        "/trade/outg", data={"node": A_URL, "Sendpoke": own, "Rec": 10}
    )
    assert application.blockchain.tradereqs == []
    # A well-formed offer is stored and sent.
    resp = client.post("/trade/outg", data={"node": B_URL, "Sendpoke": own, "Rec": 10})
    assert len(application.blockchain.tradereqs) == 1
    assert len(posts) == 1


def test_sync_adopts_longer_valid_chain():
    app_a = create_app(A_URL)
    ca = app_a.test_client()
    app_b = create_app(B_URL)
    mine(app_b)
    payload = {"chain": app_b.blockchain.chain, "length": 2}
    resp = ca.post("/node/sync", json=payload)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "adopted"}
    assert len(app_a.blockchain.chain) == 2


def test_sync_rejects_longer_invalid_chain():
    app_a = create_app(A_URL)
    ca = app_a.test_client()
    app_b = create_app(B_URL)
    mine(app_b)
    bad = copy.deepcopy(app_b.blockchain.chain)
    bad[1]["proof"] += 1
    resp = ca.post("/node/sync", json={"chain": bad, "length": 2})
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "kept"}
    assert len(app_a.blockchain.chain) == 1


def test_sync_rejects_malformed_payload():
    ca = create_app(A_URL).test_client()
    assert ca.post("/node/sync", json={}).status_code == 400
    assert ca.post("/node/sync", json={"chain": "nope"}).status_code == 400


def test_introduction_can_fetch_chain(monkeypatch):
    app_a = create_app(A_URL)
    ca = app_a.test_client()
    app_b = create_app(B_URL)
    mine(app_b)
    payload = {"chain": app_b.blockchain.chain, "length": 2}
    monkeypatch.setattr(trainer_app, "_get_json", lambda url, timeout=10: payload)
    resp = ca.post("/node", json={"node": B_URL, "fetch_chain": True})
    assert resp.status_code == 200
    assert B_URL in app_a.blockchain.nodes
    assert len(app_a.blockchain.chain) == 2


def test_introduction_survives_failed_fetch(monkeypatch):
    app_a = create_app(A_URL)
    ca = app_a.test_client()
    monkeypatch.setattr(trainer_app, "_get_json", lambda url, timeout=10: None)
    resp = ca.post("/node", json={"node": B_URL, "fetch_chain": True})
    assert resp.status_code == 200
    assert B_URL in app_a.blockchain.nodes
    assert len(app_a.blockchain.chain) == 1


def test_offer_endpoint_validates_and_dedupes():
    application = create_app(B_URL)
    client = application.test_client()
    assert client.post("/node/trade/off", json={}).status_code == 400
    assert (
        client.post(
            "/node/trade/off",
            json={"node": A_URL, "sent": 152, "rec": 10, "timestamp": 1.0},
        ).status_code
        == 400
    )
    offer = {"node": A_URL, "sent": 10, "rec": 11, "timestamp": 1.0}
    assert client.post("/node/trade/off", json=offer).status_code == 200
    assert client.post("/node/trade/off", json=offer).status_code == 200
    assert len(application.blockchain.offers) == 1


def test_transaction_endpoint_validates():
    application = create_app(A_URL)
    client = application.test_client()
    assert client.post("/node/trade", json={}).status_code == 400
    bad = {
        "trainer1": A_URL,
        "trainer2": B_URL,
        "sentby1": 152,
        "sentby2": 10,
        "time": 1.0,
    }
    assert client.post("/node/trade", json=bad).status_code == 400
    good = dict(bad, sentby1=10)
    assert client.post("/node/trade", json=good).status_code == 200
    assert len(application.blockchain.current_trade) == 1


def test_trade_pages_render():
    application = create_app(A_URL)
    client = application.test_client()
    set_user(client, "Ash")
    peer(client, B_URL)
    mine_as(application, B_URL)
    own = application.blockchain.own_pokes()[0]
    other = application.blockchain.other_pokes(B_URL)[0]
    assert b"Choose Pokemon to trade" in client.get("/trade").data
    page = client.get(f"/trade/{own}").data.decode()
    assert "Choose Pokemon to receive" in page
    assert B_URL in page
    stray = next(n for n in range(1, 152) if n not in application.blockchain.own_pokes())
    assert client.get(f"/trade/{stray}").status_code == 302
    assert client.get("/trade/outg").status_code == 200
    assert client.get("/trade/off").status_code == 200
    assert client.get("/trade/unc").status_code == 200
    assert client.get("/node/chain").get_json()["length"] == len(
        application.blockchain.chain
    )


def test_offer_response_validates():
    application = create_app(A_URL)
    client = application.test_client()
    application.blockchain.tradereqs.append(
        {"node": B_URL, "sent": 10, "rec": 11, "status": "No response yet", "timestamp": 5.0}
    )
    assert client.post("/node/trade/offerresp", json={}).status_code == 400
    assert (
        client.post(
            "/node/trade/offerresp",
            json={"node": B_URL, "tim": 5.0, "status": "Bogus"},
        ).status_code
        == 400
    )
    resp = client.post(
        "/node/trade/offerresp",
        json={"node": B_URL, "tim": 5.0, "status": "Cancelled"},
    )
    assert resp.status_code == 200
    assert application.blockchain.tradereqs[0]["status"] == "Cancelled"


def test_register_with_tracker_retries_then_gives_up(monkeypatch):
    monkeypatch.setattr(trainer_app, "_post_json", lambda *a, **k: None)
    assert register_with_tracker("http://x:1", A_URL, attempts=2, delay=0) is False
    monkeypatch.setattr(
        trainer_app, "_post_json", lambda *a, **k: SimpleNamespace(ok=True)
    )
    assert register_with_tracker("http://x:1", A_URL, attempts=1, delay=0) is True
