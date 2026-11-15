import monitor as monitor_mod
from monitor import build_dashboard, create_monitor

TRACKER = "http://127.0.0.1:5109"
A = "http://127.0.0.1:5001/node"
B = "http://127.0.0.1:5002/node"

CHAIN = [
    {"miner": A, "rew": 25, "trade": []},
    {"miner": B, "rew": 150, "trade": []},
]


def fake_network(monkeypatch, infos, unc=None, chain=CHAIN):
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
            return {"chain": chain}
        if url.endswith("/trade/unc"):
            return unc
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


def test_parser_defaults_clear_of_sim_range():
    from monitor import build_parser

    args = build_parser().parse_args([])
    assert args.port == 5300
    assert args.refresh == 15


def test_build_dashboard_uses_longest_chain(monkeypatch):
    calls = fake_network(monkeypatch, [info(A, "Ash", 3), info(B, "Misty", 9)])
    from blockchain import Blockchain
    from pokedex import load_dex

    data = build_dashboard(TRACKER, (), load_dex(), Blockchain("t"))
    assert data["chain_length"] == 2
    assert f"{B}/chain" in calls  # longest holder supplies the shared view
    assert [t["label"] for t in data["trainers"]] == ["Misty :5002", "Ash :5001"]
    assert data["total_mons"] == 2
    assert data["max_rarity"] == 5
    assert [(r["name"], r["trainer"]) for r in data["top_rares"]] == [
        ("Mewtwo", "Misty :5002")
    ]


def test_dashboard_compact_rows_sorted_by_rares(monkeypatch):
    fake_network(monkeypatch, [info(A, "Ash", 2, 1), info(B, "", 2, 0)])
    page = create_monitor(TRACKER, ()).test_client().get("/").data.decode()
    assert "<details" in page
    assert "Rarest held (R5)" in page
    assert "2 pokemon" in page
    assert "R1&times;1" in page and "R5&times;1" in page
    assert page.find("Trainer :5002") < page.find("Ash :5001")


def test_fallback_without_node_info(monkeypatch):
    from blockchain import Blockchain
    from pokedex import load_dex

    fake_network(monkeypatch, [None, None], unc=[])
    data = build_dashboard(TRACKER, (), load_dex(), Blockchain("t"))
    assert [t["label"] for t in data["trainers"]] == ["Trainer :5002", "Trainer :5001"]
    assert all(t["reachable"] for t in data["trainers"])
    assert [t["pending"] for t in data["trainers"]] == [0, 0]
    assert data["trainers"][0]["mons"][0]["name"] == "Mewtwo"
    page = create_monitor(TRACKER, ()).test_client().get("/").data.decode()
    assert "unreachable" not in page
    assert "Block ?" in page
    assert "Mewtwo" in page


def test_chain_view_renders_blocks_newest_first(monkeypatch):
    chain = [
        {
            "index": 1,
            "timestamp": 1000.0,
            "trade": [],
            "proof": 0,
            "previous_hash": "0",
            "miner": A,
            "rew": 10,
        },
        {
            "index": 2,
            "timestamp": 2000.0,
            "trade": [
                {
                    "trainer1": A,
                    "trainer2": B,
                    "sentby1": 10,
                    "sentby2": 150,
                    "time": 5.0,
                }
            ],
            "proof": 123,
            "previous_hash": "abcdef1234567890",
            "miner": B,
            "rew": 150,
        },
    ]
    fake_network(monkeypatch, [info(A, "Ash"), info(B, "Misty")], chain=chain)
    page = create_monitor(TRACKER, ()).test_client().get("/chain").data.decode()
    assert "Blockchain (2 blocks)" in page
    assert page.find("Block 2") < page.find("Block 1")
    assert "Caterpie" in page
    assert "Mewtwo" in page
    assert ">R5<" in page
    assert "Misty :5002" in page
    assert "abcdef1234567890" in page
    assert "proof 123" in page


def test_chain_view_skips_malformed(monkeypatch):
    fake_network(monkeypatch, [info(A, "Ash"), info(B, "Misty")], chain=["nope", {"index": 3}])
    page = create_monitor(TRACKER, ()).test_client().get("/chain").data.decode()
    assert "Block 3" in page
    assert "Reward: <strong>?</strong>" in page


def test_dashboard_links_to_chain(monkeypatch):
    fake_network(monkeypatch, [info(A, "Ash"), info(B, "Misty")])
    page = create_monitor(TRACKER, ()).test_client().get("/").data.decode()
    assert 'href="/chain"' in page


def test_rarest_board_tracks_top_tier(monkeypatch):
    from blockchain import Blockchain
    from pokedex import load_dex

    both = [{"miner": A, "rew": 6, "trade": []}, {"miner": B, "rew": 150, "trade": []}]
    fake_network(monkeypatch, [info(A, "Ash"), info(B, "Misty")], chain=both)
    data = build_dashboard(TRACKER, (), load_dex(), Blockchain("t"))
    assert data["max_rarity"] == 5
    assert [(r["name"], r["trainer"]) for r in data["top_rares"]] == [
        ("Mewtwo", "Misty :5002")
    ]
    common = [{"miner": A, "rew": 10, "trade": []}]
    fake_network(monkeypatch, [info(A, "Ash"), info(B, "Misty")], chain=common)
    data = build_dashboard(TRACKER, (), load_dex(), Blockchain("t"))
    assert data["max_rarity"] == 1
    assert data["top_rares"] == []
