import copy
import threading
from collections import Counter

import pytest

from blockchain import Blockchain
from pokedex import load_dex, reward_pool


@pytest.fixture(scope="module")
def dex():
    return load_dex()


def make_chain(node="A", dex=None):
    return Blockchain(node, dex=dex)


def mine(bc):
    """Mine one block with valid proof-of-work. Returns the block."""
    last = bc.last_block
    proof = bc.proof_of_work(last["proof"])
    return bc.new_block(proof, bc.hash(last))


def mine_as(bc, trainer):
    """Mine a block crediting *trainer*, restoring bc.node after."""
    old = bc.node
    bc.node = trainer
    try:
        return mine(bc)
    finally:
        bc.node = old


def test_genesis_block(dex):
    bc = make_chain("A", dex)
    assert len(bc.chain) == 1
    genesis = bc.chain[0]
    assert genesis["index"] == 1
    assert genesis["previous_hash"] == "0"
    assert genesis["proof"] == 0
    assert genesis["trade"] == []
    assert genesis["miner"] == "A"
    # Empty blocks only yield rarity-1 rewards.
    assert dex[genesis["rew"]][1] == 1


def test_lock_replaces_spinwait(dex):
    bc = make_chain("A", dex)
    assert isinstance(bc.lock, type(threading.RLock()))
    assert not hasattr(bc, "currentmining")
    with bc.lock:
        pass


def test_nodereg(dex):
    bc = make_chain("A", dex)
    bc.nodereg("B")
    bc.nodereg("B")
    assert bc.nodes == {"B"}


def test_new_transaction_queues_and_returns_next_index(dex):
    bc = make_chain("A", dex)
    idx = bc.new_transaction("A", "B", 10, 11, 123.0)
    assert idx == 2
    assert bc.current_trade == [
        {
            "trainer1": "A",
            "trainer2": "B",
            "sentby1": 10,
            "sentby2": 11,
            "time": 123.0,
        }
    ]


def test_new_transaction_normalises_dex_strings(dex):
    bc = make_chain("A", dex)
    bc.new_transaction("A", "B", "10", "11", 1.0)
    assert bc.current_trade[0]["sentby1"] == 10
    assert bc.current_trade[0]["sentby2"] == 11


def test_new_transaction_rejects_unknown_dex(dex):
    bc = make_chain("A", dex)
    with pytest.raises(ValueError):
        bc.new_transaction("A", "B", 152, 10, 1.0)
    with pytest.raises(ValueError):
        bc.new_transaction("A", "B", 10, 0, 1.0)
    with pytest.raises(ValueError):
        bc.new_transaction("A", "B", "Mew", 10, 1.0)
    assert bc.current_trade == []


def test_new_block_carries_trades_and_clears_pending(dex):
    bc = make_chain("A", dex)
    bc.new_transaction("A", "B", 10, 11, 1.0)
    block = mine(bc)
    assert len(block["trade"]) == 1
    assert block["index"] == 2
    assert block["miner"] == "A"
    assert bc.current_trade == []
    assert bc.last_block is block


def test_reward_tiers_follow_trade_count(dex):
    bc = make_chain("A", dex)
    # Empty block: rarity 1 only.
    assert dex[mine(bc)["rew"]][1] == 1
    # Busy block: reward comes from the widened pool.
    for i in range(6):
        bc.new_transaction("A", "B", 10, 11, float(i))
    rew = mine(bc)["rew"]
    assert rew in reward_pool(dex, 6)
    assert dex[rew][1] in {1, 2, 3}


def test_holdings_mining_and_trade(dex):
    bc = make_chain("A", dex)
    mine_as(bc, "A")
    mine_as(bc, "B")
    have_a = bc.holdings("A")
    have_b = bc.holdings("B")
    assert len(have_a) == 2  # genesis + mined
    assert len(have_b) == 1
    give_a, give_b = have_a[0], have_b[0]
    bc.new_transaction("A", "B", give_a, give_b, 1.0)
    valid, invalid = bc.filter_valid_trades()
    assert invalid == []
    assert len(valid) == 1
    bc.current_trade = valid
    before_a = Counter(have_a)
    before_b = Counter(have_b)
    mine(bc)
    reward = bc.last_block["rew"]
    assert Counter(bc.holdings("A")) == before_a - Counter([give_a]) + Counter(
        [give_b, reward]
    )
    assert Counter(bc.holdings("B")) == before_b - Counter([give_b]) + Counter([give_a])
    assert bc.own_pokes() == bc.holdings("A")
    assert bc.other_pokes("B") == bc.holdings("B")


def test_filter_valid_trades_chains_within_batch(dex):
    bc = make_chain("A", dex)
    mine_as(bc, "A")
    mine_as(bc, "B")
    mine_as(bc, "C")
    a_mon = bc.holdings("A")[0]
    b_mon = bc.holdings("B")[0]
    c_mon = bc.holdings("C")[0]
    pending = [
        {"trainer1": "A", "trainer2": "B",
         "sentby1": a_mon, "sentby2": b_mon, "time": 1.0},
        # B passes the just-received mon to C in the same batch.
        {"trainer1": "B", "trainer2": "C",
         "sentby1": a_mon, "sentby2": c_mon, "time": 2.0},
    ]
    valid, invalid = bc.filter_valid_trades(pending)
    assert invalid == []
    assert valid == pending


def test_filter_valid_trades_catches_consecutive_invalid(dex):
    """Regression: the old loop removed items while iterating and skipped
    every second invalid trade. All three invalid trades must be caught."""
    bc = make_chain("A", dex)
    mine_as(bc, "A")
    mine_as(bc, "B")
    a_mon = bc.holdings("A")[0]
    b_mon = bc.holdings("B")[0]
    owned = set(bc.holdings("A")) | set(bc.holdings("B"))
    # Dex numbers neither trainer owns.
    strays = [n for n in range(1, 152) if n not in owned][:3]
    pending = [
        {"trainer1": "A", "trainer2": "B",
         "sentby1": strays[0], "sentby2": b_mon, "time": 1.0},
        {"trainer1": "A", "trainer2": "B",
         "sentby1": a_mon, "sentby2": strays[1], "time": 2.0},
        {"trainer1": "A", "trainer2": "B",
         "sentby1": strays[2], "sentby2": strays[1], "time": 3.0},
        {"trainer1": "A", "trainer2": "B",
         "sentby1": a_mon, "sentby2": b_mon, "time": 4.0},
    ]
    valid, invalid = bc.filter_valid_trades(pending)
    assert len(invalid) == 3
    assert len(valid) == 1
    assert valid[0]["time"] == 4.0


def test_filter_valid_trades_does_not_mutate_input(dex):
    bc = make_chain("A", dex)
    pending = [
        {"trainer1": "A", "trainer2": "B",
         "sentby1": 10, "sentby2": 11, "time": 1.0},
    ]
    snapshot = copy.deepcopy(pending)
    bc.filter_valid_trades(pending)
    assert pending == snapshot


def test_prune_confirmed_trades(dex):
    bc = make_chain("A", dex)
    mine_as(bc, "A")
    mine_as(bc, "B")
    a_mon = bc.holdings("A")[0]
    b_mon = bc.holdings("B")[0]
    t1 = {"trainer1": "A", "trainer2": "B",
          "sentby1": a_mon, "sentby2": b_mon, "time": 1.0}
    t2 = {"trainer1": "A", "trainer2": "B",
          "sentby1": a_mon, "sentby2": b_mon, "time": 2.0}
    bc.current_trade = [dict(t1), dict(t2)]
    # Mine t1 on a fork, then adopt it: only t2 should remain queued.
    fork = copy.deepcopy(bc.chain)
    last = fork[-1]
    tmp = make_chain("A", dex)
    tmp.chain = copy.deepcopy(fork)
    tmp.current_trade = [dict(t1)]
    mined = mine(tmp)
    fork.append(mined)
    assert bc.replace_chain(fork) is True
    assert bc.current_trade == [t2]


def test_proof_of_work_finds_valid_proof(dex):
    bc = make_chain("A", dex)
    last = bc.last_block
    proof = bc.proof_of_work(last["proof"])
    assert bc.valid_proof(last["proof"], proof, bc.hash(last))


def test_valid_chain_accepts_mined(dex):
    bc = make_chain("A", dex)
    mine(bc)
    mine(bc)
    assert bc.valid_chain(bc.chain) is True
    assert bc.valid_chain(copy.deepcopy(bc.chain)) is True


def test_valid_chain_rejects_tampered_trade(dex):
    bc = make_chain("A", dex)
    mine_as(bc, "A")
    mine_as(bc, "B")
    a_mon = bc.holdings("A")[0]
    b_mon = bc.holdings("B")[0]
    bc.new_transaction("A", "B", a_mon, b_mon, 1.0)
    mine(bc)
    owned = set(bc.holdings("A")) | set(bc.holdings("B"))
    stray = next(n for n in range(1, 152) if n not in owned)
    tampered = copy.deepcopy(bc.chain)
    tampered[3]["trade"][0]["sentby1"] = stray
    assert bc.valid_chain(tampered) is False


def test_valid_chain_rejects_bad_previous_hash(dex):
    bc = make_chain("A", dex)
    mine(bc)
    tampered = copy.deepcopy(bc.chain)
    tampered[1]["previous_hash"] = "deadbeef"
    assert bc.valid_chain(tampered) is False


def test_valid_chain_rejects_bad_proof(dex):
    bc = make_chain("A", dex)
    mine(bc)
    tampered = copy.deepcopy(bc.chain)
    tampered[1]["proof"] += 1
    assert bc.valid_chain(tampered) is False


def test_valid_chain_rejects_trade_for_unowned_mon(dex):
    bc = make_chain("A", dex)
    # Queue a trade for mons nobody owns and mine it with valid PoW.
    bc.new_transaction("A", "B", 10, 11, 1.0)
    mine(bc)
    assert bc.valid_chain(bc.chain) is False


def test_valid_chain_rejects_bad_reward_tier(dex):
    bc = make_chain("A", dex)
    tampered = copy.deepcopy(bc.chain)
    tampered[0]["rew"] = 151  # Mew (rarity 5) from an empty genesis block.
    assert bc.valid_chain(tampered) is False
    assert bc.valid_chain([]) is False


def test_replace_chain_accepts_longer_valid(dex):
    bc = make_chain("A", dex)
    longer = make_chain("A", dex)
    # Sync genesis rewards so the longer chain links onto ours.
    longer.chain = copy.deepcopy(bc.chain)
    longer.node = "A"
    mine(longer)
    assert bc.replace_chain(copy.deepcopy(longer.chain)) is True
    assert len(bc.chain) == 2


def test_replace_chain_rejects_longer_invalid(dex):
    bc = make_chain("A", dex)
    longer = make_chain("A", dex)
    longer.chain = copy.deepcopy(bc.chain)
    mine(longer)
    bad = copy.deepcopy(longer.chain)
    bad[1]["trade"] = [
        {"trainer1": "A", "trainer2": "B",
         "sentby1": 10, "sentby2": 11, "time": 1.0}
    ]
    before = copy.deepcopy(bc.chain)
    assert bc.replace_chain(bad) is False
    assert bc.chain == before


def test_replace_chain_rejects_shorter_or_equal(dex):
    bc = make_chain("A", dex)
    mine(bc)
    assert bc.replace_chain(copy.deepcopy(bc.chain)) is False
    assert bc.replace_chain(copy.deepcopy(bc.chain[:1])) is False
