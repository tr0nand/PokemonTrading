# PokemonTrading

A blockchain-based Pokemon trading game. Be the ultimate Pokemon master and
catch all 151 Gen-1 Pokemon: mine blocks to capture Pokemon, then trade them
with other trainers over a shared distributed ledger. Gotta catch 'em all.

## Quickstart

Requirements: Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python demo.py
```

Then open http://127.0.0.1:5010 in your browser (and :5011 for a second
trainer). `demo.py` starts a tracker plus two trainers; Ctrl-C stops
everything. Options: `--tracker-port`, `--trainers`, `--base-port`.

To run processes by hand instead:

```bash
python nodetracker.py 5009
python app.py 5009 5010   # tracker port, then this trainer's port
python app.py 5009 5011
```

## How to play

1. Enter a trainer name on each trainer's page.
2. Press **Mine** to forge a block and capture its reward Pokemon.
3. Press **Trade**, pick one of your Pokemon, then pick a Pokemon another
   trainer owns. They accept (or reject) from Trade Offers; once a block
   carrying the trade is mined, the request shows Verified.

Mining incentives: empty blocks only yield common (rarity-1) Pokemon, while
blocks carrying more trades unlock rarer ones — up to rarity-5 legendaries
at 20+ trades.

## How it works

One tracker process introduces trainers to each other; each trainer runs its
own Flask app holding a full copy of the chain. Consensus is
longest-valid-chain: a trainer only adopts a longer chain whose hashes link,
whose proofs meet the difficulty (SHA-256 starting with `0000`), whose
rewards fit their trade counts, and whose trades spend Pokemon the traders
actually own. Pending trades are validated without mutating the queue, and a
re-entrant lock guards chain state instead of a spin-wait.

## Testing

```bash
source .venv/bin/activate
python -m pytest tests/ -q
```

## Layout

- `app.py` — trainer node (browser UI + peer API)
- `nodetracker.py` — trainer registry
- `blockchain.py` — blocks, trades, proof-of-work, consensus
- `pokedex.py` — Gen-1 dex lookups and reward pools (`Kanto.csv`)
- `demo.py` — one-command local game
- `templates/` + `static/` — pages, sprites, styles

## Known limits

Chains live in memory: restarting a trainer resets it to a fresh genesis
block. Peer endpoints have no authentication, so only play on localhost.
