import pytest

from pokedex import load_dex, pokemon_name, reward_pool


@pytest.fixture(scope="module")
def dex():
    return load_dex()


def test_loads_all_151(dex):
    assert len(dex) == 151
    assert set(dex) == set(range(1, 152))


def test_known_names(dex):
    assert pokemon_name(dex, 1) == "Bulbasaur"
    assert pokemon_name(dex, 25) == "Pikachu"
    assert pokemon_name(dex, 151) == "Mew"


def test_unknown_nat_raises(dex):
    with pytest.raises(KeyError):
        pokemon_name(dex, 152)


def test_empty_block_yields_only_common(dex):
    pool = reward_pool(dex, 0)
    assert pool
    assert all(dex[n][1] == 1 for n in pool)
    assert 10 in pool  # Caterpie, rarity 1
    assert 1 not in pool  # Bulbasaur, rarity 2


def test_busier_blocks_unlock_rarer(dex):
    assert 1 in reward_pool(dex, 1)  # rarity 2 from 1 trade
    assert 2 in reward_pool(dex, 5)  # Ivysaur, rarity 3
    assert 6 in reward_pool(dex, 10)  # Charizard, rarity 4
    assert 151 in reward_pool(dex, 20)  # Mew, rarity 5
    assert 151 not in reward_pool(dex, 19)


def test_pools_grow_monotonically(dex):
    sizes = [len(reward_pool(dex, n)) for n in (0, 1, 5, 10, 20)]
    assert sizes == sorted(sizes)
    assert len(set(sizes)) > 1


def test_negative_trade_count_raises(dex):
    with pytest.raises(ValueError):
        reward_pool(dex, -1)
