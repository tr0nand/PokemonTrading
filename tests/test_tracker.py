import requests

import nodetracker
from nodetracker import create_tracker


A = "http://127.0.0.1:5001/node"
B = "http://127.0.0.1:5002/node"


def test_register_first_node_has_no_peers(monkeypatch):
    calls = []
    monkeypatch.setattr(
        nodetracker, "announce", lambda url, payload: calls.append((url, payload))
    )
    client = create_tracker().test_client()
    resp = client.post("/nodes", json={"node": A})
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "registered", "node": A, "peers": []}
    assert calls == []
    assert client.get("/nodes").get_json() == {"nodes": [A]}


def test_register_second_introduces_both_ways(monkeypatch):
    calls = []
    monkeypatch.setattr(
        nodetracker, "announce", lambda url, payload: calls.append((url, payload))
    )
    client = create_tracker().test_client()
    client.post("/nodes", json={"node": A})
    resp = client.post("/nodes", json={"node": B})
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "registered", "node": B, "peers": [A]}
    # Established peer just records the newcomer; the newcomer is told to
    # fetch the chain from the established peer.
    assert calls == [
        (A, {"node": B, "fetch_chain": False}),
        (B, {"node": A, "fetch_chain": True}),
    ]
    assert client.get("/nodes").get_json() == {"nodes": [A, B]}


def test_duplicate_registration_is_quiet(monkeypatch):
    calls = []
    monkeypatch.setattr(
        nodetracker, "announce", lambda url, payload: calls.append((url, payload))
    )
    client = create_tracker().test_client()
    client.post("/nodes", json={"node": A})
    client.post("/nodes", json={"node": B})
    before = len(calls)
    resp = client.post("/nodes", json={"node": A})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "already known"
    assert len(calls) == before
    assert client.get("/nodes").get_json() == {"nodes": [A, B]}


def test_rejects_bad_payloads():
    client = create_tracker().test_client()
    for body in (None, {}, {"node": 123}, {"node": "  "}, {"node": "ftp://x"}):
        resp = client.post("/nodes", json=body)
        assert resp.status_code == 400, body
    assert client.get("/nodes").get_json() == {"nodes": []}


def test_dead_peer_does_not_break_registration(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(nodetracker.requests, "post", boom)
    client = create_tracker().test_client()
    assert client.post("/nodes", json={"node": A}).status_code == 200
    resp = client.post("/nodes", json={"node": B})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "registered"
    assert client.get("/nodes").get_json() == {"nodes": [A, B]}


def test_rejects_oversized_body():
    application = create_tracker()
    application.config["MAX_CONTENT_LENGTH"] = 100
    client = application.test_client()
    resp = client.post("/nodes", json={"node": "x" * 1000})
    assert resp.status_code == 413
