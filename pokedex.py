"""Gen-1 Pokedex lookups and mining reward pools.

Fresh rewrite of the old pokemon.py plus the inline pandas lookups in
app.py/blockchain.py. Uses only the csv stdlib module. Data comes from
Kanto.csv: Nat,Pokemon,...,Rarity where rarity runs 1 (common) to 6
(mythic: Mewtwo and Mew only).
"""

import csv
from pathlib import Path

DATA_PATH = Path(__file__).with_name("Kanto.csv")


def load_dex(path=DATA_PATH):
    """Load the dex file into {nat: (name, rarity)}."""
    dex = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            dex[int(row["Nat"])] = (row["Pokemon"], int(row["Rarity"]))
    return dex


def pokemon_name(dex, nat):
    """Return the Pokemon name for a dex number. Raises KeyError if unknown."""
    return dex[int(nat)][0]


def reward_pool(dex, trade_count):
    """Dex numbers eligible as a mining reward for a block carrying trade_count trades.

    Empty blocks can only yield rarity-1 Pokemon, and busier blocks unlock
    rarer tiers, up to the rarity-6 mythics at 40+ trades.
    """
    if trade_count < 0:
        raise ValueError(f"trade count cannot be negative: {trade_count}")
    if trade_count == 0:
        allowed = {1}
    elif trade_count < 5:
        allowed = {1, 2}
    elif trade_count < 10:
        allowed = {1, 2, 3}
    elif trade_count < 20:
        allowed = {1, 2, 3, 4}
    elif trade_count < 40:
        allowed = {1, 2, 3, 4, 5}
    else:
        allowed = {1, 2, 3, 4, 5, 6}
    return sorted(n for n, (_, rarity) in dex.items() if rarity in allowed)
