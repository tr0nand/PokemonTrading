import monitor as monitor_mod
from monitor import build_dashboard, create_monitor

TRACKER = "http://127.0.0.1:5109"
A = "http://127.0.0.1:5001/node"
B = "http://127.0.0.1:5002/node"

CHAIN = [
    {"miner": A, "rew": 25, "trade": []},
    {"miner": B, "rew": 150, "trade": []},
]


def fake_network(monkeypatch, infos):
    calls = []

    def fake(url, timeout):
        calls.append(url)
        if url == f"{TRACKER}/nodes":
            return {"nodes": [A, B]}
        if url == f"{A}/info":
            return infos[0]
        if url == f"{B}/info":
            return infos[1]
        if url in (f"{A}/chain", f"{B}/chain"):
            return {"chain": CHAIN}
        raise AssertionError(f"unexpected {url}")

    monkeypatch.setattr(monitor_mod, "_get_json", fake)
    return calls


def info(node, user, length=2, pending=0):
    return {"node": node, "user": user, "length": length, "pending": pending}


def test_dashboard_renders_trainers_and_rares(monkeypatch):
    fake_network(monkeypatch, [info(A, "Ash", 2, 1), info(B, "", 2, 0)])
    page = create_monitor(TRACKER, (), refresh=7).test_client().get("/").data.decode()
    assert "2 trainers" in page
    assert "longest chain 2" in page
    assert 'content="7"' in page
    assert "Ash :5001" in page
    assert "Trainer :5002" in page
    assert "Pikachu" in page
    assert "Mewtwo" in page
    assert ">R5<" in page
    assert "1 pending" in page


def test_explicit_trainers_skip_tracker(monkeypatch):
    calls = fake_network(monkeypatch, [info(A, "Ash"), None])
    client = create_monitor(None, [A, B]).test_client()
    page = client.get("/").data.decode()
    assert not [u for u in calls if u.endswith("/nodes")]
    assert "Ash :5001" in page
    assert "unreachable" in page


def test_empty_network_renders_notice(monkeypatch):
    monkeypatch.setattr(monitor_mod, "_get_json", lambda url, timeout: {"nodes": []})
    page = create_monitor(TRACKER, ()).test_client().get("/").data.decode()
    assert "0 trainers" in page
    assert "No trainers found" in page


def test_build_dashboard_uses_longest_chain(monkeypatch):
    calls = fake_network(monkeypatch, [info(A, "Ash", 3), info(B, "Misty", 9)])
    from blockchain import Blockchain
    from pokedex import load_dex

    data = build_dashboard(TRACKER, (), load_dex(), Blockchain("t"))
    assert data["chain_length"] == 2
    assert f"{B}/chain" in calls  # longest holder supplies the shared view
    assert [t["label"] for t in data["trainers"]] == ["Ash :5001", "Misty :5002"]
