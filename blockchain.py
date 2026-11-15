"""Pokemon trading blockchain: blocks, trades, proof-of-work, consensus.

Fresh rewrite of the original blockchain.py. Block schema and proof-of-work
are faithful to the 2018 game; the known defects are fixed:

- Dex lookups use :mod:`pokedex` (csv stdlib) instead of pandas.
- Pending-trade validation partitions into valid/invalid lists instead of
  removing entries from the list being iterated (which skipped trades).
- Incoming chains are accepted only when longer *and* valid
  (:meth:`Blockchain.valid_chain`); the original trusted any longer chain.
- A re-entrant thread lock (:attr:`Blockchain.lock`) guards chain state
  instead of the ``currentmining`` spin-wait flag.
"""

import hashlib
import json
import random
import threading
from time import time

from pokedex import load_dex, reward_pool

DIFFICULTY_PREFIX = "0000"


class Blockchain:
    """One trainer's view of the shared Pokemon chain."""

    def __init__(self, node, dex=None):
        self.node = node
        self.chain = []
        self.current_trade = []
        self.nodes = set()
        self.user = ""
        self.tradereqs = []
        self.offers = []
        # Guards chain/current_trade/nodes. Re-entrant so compound
        # operations (mine, sync) can hold it across helper calls.
        self.lock = threading.RLock()
        self.dex = dex if dex is not None else load_dex()
        self.new_block(proof=0, previous_hash="0")

    # -- membership ----------------------------------------------------
    def nodereg(self, node):
        """Register a peer trainer node address."""
        with self.lock:
            self.nodes.add(node)

    # -- blocks --------------------------------------------------------
    @property
    def last_block(self):
        return self.chain[-1]

    @staticmethod
    def hash(block):
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def new_transaction(self, trainer1, trainer2, sentby1, sentby2, timesent):
        """Queue a trade for the next mined block.

        Ownership is checked at mining time, but the offered dex numbers
        must exist; they are normalised to int so local and
        network-received trades compare equal.
        """
        try:
            sentby1 = int(sentby1)
            sentby2 = int(sentby2)
        except (TypeError, ValueError):
            raise ValueError("offered Pokemon must be dex numbers")
        if sentby1 not in self.dex or sentby2 not in self.dex:
            raise ValueError("unknown dex number in trade")
        if not trainer1 or not trainer2:
            raise ValueError("trade needs both trainers")
        trade = {
            "trainer1": trainer1,
            "trainer2": trainer2,
            "sentby1": sentby1,
            "sentby2": sentby2,
            "time": timesent,
        }
        with self.lock:
            self.current_trade.append(trade)
            return self.last_block["index"] + 1

    def new_block(self, proof, previous_hash=None):
        """Forge a block carrying the currently queued trades."""
        with self.lock:
            if not self.chain and previous_hash is None:
                raise ValueError("genesis block needs an explicit previous_hash")
            trades = list(self.current_trade)
            self.current_trade = []
            block = {
                "index": len(self.chain) + 1,
                "timestamp": time(),
                "trade": trades,
                "proof": proof,
                "previous_hash": (
                    previous_hash
                    if previous_hash is not None
                    else self.hash(self.chain[-1])
                ),
                "miner": self.node,
            }
            block["rew"] = random.choice(reward_pool(self.dex, len(trades)))
            self.chain.append(block)
            return block

    # -- proof of work -------------------------------------------------
    def proof_of_work(self, last_proof):
        with self.lock:
            last_hash = self.hash(self.chain[-1])
        proof = 0
        while not self.valid_proof(last_proof, proof, last_hash):
            proof += 1
        return proof

    @staticmethod
    def valid_proof(last_proof, proof, last_hash):
        guess = str(str(last_proof + proof) + str(last_hash)).encode()
        return hashlib.sha256(guess).hexdigest()[:4] == DIFFICULTY_PREFIX

    # -- holdings ------------------------------------------------------
    def holdings(self, trainer, chain=None):
        """Dex numbers owned by *trainer* after replaying *chain*.

        Rewards credit the miner; each trade moves the offered mons.
        Removals that do not match anything held are ignored so a
        tampered chain yields a best-effort view instead of raising.
        """
        with self.lock:
            blocks = list(chain if chain is not None else self.chain)
        caught = []
        given_away = []
        for block in blocks:
            if block.get("miner") == trainer:
                caught.append(int(block["rew"]))
            for trade in block.get("trade", []):
                if trade.get("trainer1") == trainer:
                    caught.append(int(trade["sentby2"]))
                    given_away.append(int(trade["sentby1"]))
                elif trade.get("trainer2") == trainer:
                    caught.append(int(trade["sentby1"]))
                    given_away.append(int(trade["sentby2"]))
        for nat in given_away:
            try:
                caught.remove(nat)
            except ValueError:
                continue
        return caught

    def own_pokes(self):
        return self.holdings(self.node)

    def other_pokes(self, nodel):
        return self.holdings(nodel)

    # -- pending-trade validation --------------------------------------
    def filter_valid_trades(self, pending=None, chain=None):
        """Split pending trades into (valid, invalid) without mutating input.

        Each trade is checked against simulated holdings that include the
        effects of earlier valid trades in the same batch, mirroring the
        order they would be mined in.
        """
        with self.lock:
            batch = list(
                pending if pending is not None else self.current_trade
            )
            snapshot = list(chain if chain is not None else self.chain)
        balances = {}

        def balance(trainer):
            if trainer not in balances:
                balances[trainer] = self.holdings(trainer, chain=snapshot)
            return balances[trainer]

        valid = []
        invalid = []
        for trade in batch:
            try:
                trainer1 = trade["trainer1"]
                trainer2 = trade["trainer2"]
                sentby1 = int(trade["sentby1"])
                sentby2 = int(trade["sentby2"])
            except (KeyError, TypeError, ValueError):
                invalid.append(trade)
                continue
            have1 = balance(trainer1)
            have2 = balance(trainer2)
            if sentby1 in have1 and sentby2 in have2:
                valid.append(trade)
                if trainer1 == trainer2:
                    continue
                have1.remove(sentby1)
                have1.append(sentby2)
                have2.remove(sentby2)
                have2.append(sentby1)
            else:
                invalid.append(trade)
        return valid, invalid

    @staticmethod
    def _trade_key(trade):
        return (
            trade.get("trainer1"),
            trade.get("trainer2"),
            str(trade.get("sentby1")),
            str(trade.get("sentby2")),
            str(trade.get("time")),
        )

    def prune_confirmed_trades(self):
        """Drop queued trades already present in the chain. Returns count."""
        with self.lock:
            confirmed = {
                self._trade_key(trade)
                for block in self.chain
                for trade in block.get("trade", [])
            }
            kept = [
                trade
                for trade in self.current_trade
                if self._trade_key(trade) not in confirmed
            ]
            removed = len(self.current_trade) - len(kept)
            self.current_trade = kept
            return removed

    # -- consensus -----------------------------------------------------
    def valid_chain(self, chain):
        """Check linkage, proof-of-work, reward tiers, and trade ownership."""
        if not chain:
            return False
        genesis = chain[0]
        if not isinstance(genesis, dict):
            return False
        if (
            genesis.get("index") != 1
            or genesis.get("previous_hash") != "0"
            or genesis.get("proof") != 0
            or not isinstance(genesis.get("trade"), list)
            or "rew" not in genesis
            or not isinstance(genesis.get("miner"), str)
        ):
            return False
        try:
            if int(genesis["rew"]) not in reward_pool(
                self.dex, len(genesis["trade"])
            ):
                return False
        except (TypeError, ValueError, KeyError):
            return False

        balances = {}

        def balance(trainer):
            return balances.setdefault(trainer, [])

        try:
            balance(genesis["miner"]).append(int(genesis["rew"]))
        except (TypeError, ValueError, KeyError):
            return False

        prev = genesis
        for block in chain[1:]:
            if not isinstance(block, dict):
                return False
            for key in (
                "index",
                "timestamp",
                "trade",
                "proof",
                "previous_hash",
                "miner",
                "rew",
            ):
                if key not in block:
                    return False
            if not isinstance(block["trade"], list):
                return False
            if not isinstance(block["miner"], str):
                return False
            if not isinstance(block["proof"], int):
                return False
            if block["index"] != prev["index"] + 1:
                return False
            prev_hash = self.hash(prev)
            if block["previous_hash"] != prev_hash:
                return False
            if not self.valid_proof(prev["proof"], block["proof"], prev_hash):
                return False
            try:
                if int(block["rew"]) not in reward_pool(
                    self.dex, len(block["trade"])
                ):
                    return False
            except (TypeError, ValueError):
                return False
            for trade in block["trade"]:
                try:
                    trainer1 = trade["trainer1"]
                    trainer2 = trade["trainer2"]
                    sentby1 = int(trade["sentby1"])
                    sentby2 = int(trade["sentby2"])
                except (KeyError, TypeError, ValueError):
                    return False
                if not isinstance(trainer1, str) or not isinstance(trainer2, str):
                    return False
                have1 = balance(trainer1)
                have2 = balance(trainer2)
                if sentby1 not in have1 or sentby2 not in have2:
                    return False
                if trainer1 != trainer2:
                    have1.remove(sentby1)
                    have1.append(sentby2)
                    have2.remove(sentby2)
                    have2.append(sentby1)
            try:
                balance(block["miner"]).append(int(block["rew"]))
            except (TypeError, ValueError):
                return False
            prev = block
        return True

    def replace_chain(self, new_chain):
        """Adopt *new_chain* when it is longer and valid. Returns bool."""
        with self.lock:
            if not isinstance(new_chain, list):
                return False
            if len(new_chain) <= len(self.chain):
                return False
            if not self.valid_chain(new_chain):
                return False
            try:
                self.chain = json.loads(json.dumps(new_chain))
            except (TypeError, ValueError):
                return False
            self.prune_confirmed_trades()
            return True
