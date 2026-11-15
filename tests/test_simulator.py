import random

import pytest
import requests

from simulator import (
    Sim,
    build_parser,
    choose_miner,
    parse_weights,
    summarize_holdings,
    with_retries,
)


def test_parse_weights_valid():
    assert parse_weights("50,25,25", 3) == [50.0, 25.0, 25.0]
    assert parse_weights("1,1", 2) == [1.0, 1.0]


def test_parse_weights_rejects_bad_specs():
    with pytest.raises(ValueError):
        parse_weights("50,25", 3)  # count mismatch
    with pytest.raises(ValueError):
        parse_weights("50,xx", 2)  # non-numeric
    with pytest.raises(ValueError):
        parse_weights("50,-5", 2)  # negative
    with pytest.raises(ValueError):
        parse_weights("0,0", 2)  # all zero


def test_choose_miner_respects_weights():
    assert choose_miner([1.0, 0.0], random.Random(0)) == 0
    assert choose_miner([0.0, 5.0], random.Random(0)) == 1
    rng1, rng2 = random.Random(42), random.Random(42)
    first = [choose_miner([3.0, 1.0], rng1) for _ in range(50)]
    second = [choose_miner([3.0, 1.0], rng2) for _ in range(50)]
    assert first == second  # seeded runs reproduce
    assert set(first) == {0, 1}  # both miners get picked


def test_summarize_holdings_counts_and_rares():
    dex = {10: ("Caterpie", 1), 150: ("Mewtwo", 5), 151: ("Mew", 5), 6: ("Charizard", 4)}
    summary = summarize_holdings({0: [10, 150], 1: [6, 151], 2: []}, dex)
    assert summary["by_rarity"] == {1: 1, 2: 0, 3: 0, 4: 1, 5: 2}
    assert [(r["owner"], r["name"]) for r in summary["rares"]] == [
        (1, "Mew"),
        (0, "Mewtwo"),
        (1, "Charizard"),
    ]


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.trainers == 20
    assert args.minutes == 20
    assert args.miner_weights is None
    assert args.eagerness == 2.0
    assert args.accept_rate == 1.0
    assert args.fair_only is False
    assert args.serve_after is False
    assert args.startup_stagger == 1.0
    assert args.funding_settle == 1.0
    assert args.chain_cache == 10.0
    assert args.min_round_interval == 15.0


def test_with_retries_recovers_and_gives_up():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise requests.ConnectionError("down")
        return "ok"

    assert with_retries(flaky, delay=0) == "ok"
    assert len(calls) == 3

    def dead():
        raise requests.ConnectionError("down")

    with pytest.raises(requests.ConnectionError):
        with_retries(dead, attempts=2, delay=0)


def test_shared_chain_caches_within_ttl(monkeypatch):
    from types import SimpleNamespace

    args = build_parser().parse_args(["--trainers", "3", "--chain-cache", "100"])
    sim = Sim(args)
    calls = []

    def fake_get(*get_args, **kwargs):
        calls.append(1)
        return SimpleNamespace(json=lambda: {"chain": [1, 2]})

    monkeypatch.setattr(sim.session, "get", fake_get)
    assert sim.shared_chain() == [1, 2]
    assert sim.shared_chain() == [1, 2]
    assert len(calls) == 1

    uncached = Sim(build_parser().parse_args(["--trainers", "3", "--chain-cache", "0"]))
    monkeypatch.setattr(uncached.session, "get", fake_get)
    uncached.shared_chain()
    uncached.shared_chain()
    assert len(calls) == 3


def test_verify_servers_pass_and_fail(monkeypatch):
    from types import SimpleNamespace

    sim = Sim(build_parser().parse_args(["--trainers", "2"]))

    def ok(url, timeout):
        if url.endswith("/nodes"):
            return SimpleNamespace(json=lambda: {"nodes": []})
        return SimpleNamespace(text='<form><input name="user">')

    monkeypatch.setattr(sim.session, "get", ok)
    sim.verify_servers(timeout=5)  # returns cleanly

    def wrong_app(url, timeout):
        if url.endswith("/nodes"):
            return SimpleNamespace(json=lambda: {"nodes": []})
        return SimpleNamespace(text="<title>Trainer Monitor</title>")

    monkeypatch.setattr(sim.session, "get", wrong_app)
    with pytest.raises(SystemExit):
        sim.verify_servers(timeout=0.05)

    def down(url, timeout):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(sim.session, "get", down)
    with pytest.raises(SystemExit):
        sim.verify_servers(timeout=0.05)


def test_checked_get_raises_on_http_error(monkeypatch):
    sim = Sim(build_parser().parse_args(["--trainers", "2"]))

    class Resp404:
        status_code = 404

        def raise_for_status(self):
            raise requests.HTTPError("404 Client Error")

    monkeypatch.setattr(sim.session, "get", lambda *a, **k: Resp404())
    with pytest.raises(requests.HTTPError):
        sim._checked_get("http://x/mine", 5)
