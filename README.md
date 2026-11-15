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

## Simulator

`simulator.py` runs a bot network on its own ports (tracker :5109, trainers
:5110+, separate from `demo.py`) to exercise trading and mining at scale:

```bash
python simulator.py --trainers 20 --minutes 20
python simulator.py --trainers 4 --miner-weights 50,25,12.5,12.5 \
    --eagerness 3 --accept-rate 0.8 --fair-only --seed 7 --serve-after
```

Knobs: `--trainers` (bot count), `--miner-weights` (per-trainer mining
share, default uniform), `--eagerness` (mean trades/sec/bot),
`--accept-rate` (offer acceptance probability), `--fair-only` (bots reject
rarity-losing trades), plus `--minutes`, `--target-pending`,
`--funding-rounds`, `--seed`, `--results`, `--log`, and `--serve-after` to
keep browsing when the run ends. Results land in `sim_results.json`
(ignored by git).

Pacing knobs keep big runs inside what localhost can sustain (the dev
server closes every connection, so request volume is the limit):
`--startup-stagger`, `--funding-settle`, `--chain-cache` (shared chain
snapshot TTL), and `--min-round-interval`.

## Monitor

`monitor.py` watches a running network and shows every trainer's current
collection on one auto-refreshing page, with rarity-4/5 catches called out:

```bash
python monitor.py --tracker http://127.0.0.1:5109 --port 5200
python monitor.py --trainers http://127.0.0.1:5010/node,http://127.0.0.1:5011/node
```

Then open the monitor port in a browser. It discovers trainers from the
tracker (or takes an explicit list), reads one status snapshot per trainer
plus the longest chain once, and refreshes every `--refresh` seconds
(default 15).

## Layout

- `app.py` — trainer node (browser UI + peer API)
- `nodetracker.py` — trainer registry
- `blockchain.py` — blocks, trades, proof-of-work, consensus
- `pokedex.py` — Gen-1 dex lookups and reward pools (`Kanto.csv`)
- `demo.py` — one-command local game
- `simulator.py` — configurable bot network for experiments
- `monitor.py` — live dashboard of every trainer's collection
- `templates/` + `static/` — pages, sprites, styles

## Known limits

Chains live in memory: restarting a trainer resets it to a fresh genesis
block. Peer endpoints have no authentication, so only play on localhost.
