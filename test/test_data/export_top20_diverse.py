#!/usr/bin/env python3
"""Export the top 20 distinct qualifying bots across diverse strategy families into test/bots/."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
BOTS_DIR = ROOT.parent / "bots"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BOTS_DIR))

import bot_runtime

from generate_and_qualify import build_systematic_candidates
from qualify_bots import export_standalone_bot

q = json.loads((ROOT / "qualification_log.json").read_text(encoding="utf-8"))
specs = {s["slug"]: s for s in build_systematic_candidates()}

# Deduplicate candidates by unique slug and keep highest ranking
seen_slugs = set()
unique_candidates = []
for c in q["candidates"]:
    if c["eligible"] and c["slug"] not in seen_slugs:
        seen_slugs.add(c["slug"])
        unique_candidates.append(c)

print(f"Total unique qualified bots available: {len(unique_candidates)}")

# Select top 20 distinct bots
selected = unique_candidates[:20]

# Clean existing bot_*.py files in test/bots/
for old in BOTS_DIR.glob("bot_[0-9][0-9]_*.py"):
    old.unlink()

manifest = []
for idx, c in enumerate(selected, 1):
    slug = c["slug"]
    sp = specs[slug]
    bot_file = export_standalone_bot(idx, sp, c)
    bot_id = bot_file.stem
    print(f"  [{idx:2d}/20] Exported {bot_id} | Net: Rs {c['net_pnl']:+10,.2f} | PF: {c['profit_factor']:4.2f} | {c['family']}")

    # Copy / save trade log and daily PnL
    tdir = ROOT / "bot_trades" / bot_id
    tdir.mkdir(parents=True, exist_ok=True)
    if "daily_rows" in c and c["daily_rows"]:
        with (tdir / "daily_pnl.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(c["daily_rows"][0].keys()))
            w.writeheader()
            w.writerows(c["daily_rows"])
    if "trades" in c and c["trades"]:
        tfields = ["key", "kind", "strike", "setup", "entered", "exited", "quantity", "entry", "exit", "net_pnl", "charges", "reason"]
        with (tdir / "trades.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=tfields)
            w.writeheader()
            for t in c["trades"]:
                w.writerow({k: t.get(k, "") for k in tfields})

    item = {
        "bot_id": bot_id,
        "bot_name": c["bot_name"],
        "family": c["family"],
        "slug": slug,
        "file": bot_file.name,
        "net_pnl": c["net_pnl"],
        "return_pct": c["return_pct"],
        "closed_trades": c["closed_trades"],
        "wins": c["wins"],
        "losses": c["losses"],
        "win_rate_pct": c["win_rate_pct"],
        "profit_factor": c["profit_factor"],
        "max_drawdown": c["max_drawdown"],
        "active_days": c["active_days"],
        "observed_days": c["observed_days"],
        "daily_coverage_pct": c["daily_coverage_pct"],
        "avg_trades_per_day": c["avg_trades_per_day"],
    }
    manifest.append(item)

# Re-run fast evaluation on all 20 to attach full daily_rows for the round-robin tournament
import pickle
from bot_runtime import CompetitionBotEngine, Blocked
from qualify_bots import _compile_fn

with (ROOT / "market_cache" / "fast_stream.pkl").open("rb") as f:
    stream = pickle.load(f)

for item in manifest:
    sp = specs[item["slug"]]
    sig_fn = _compile_fn(sp["signal_code"], "evaluate_signal")
    ex_fn = _compile_fn(sp["exit_code"], "evaluate_exit")
    cfg = {**bot_runtime.BASE_BOT_CONFIG, **sp["config"], "initial_wallet": 50000.0}
    eng = CompetitionBotEngine(item["bot_id"], item["bot_name"], cfg, sig_fn, ex_fn, persist=False)
    for day_str, rows in stream:
        for ts_str, now_dt, d_s, clk, vix_v, opts, feat in rows:
            try:
                eng.fast_step(ts_str, now_dt, d_s, clk, vix_v, opts, feat)
            except Blocked:
                pass
    item["daily_rows"] = eng.daily_rows()
    # Also save trades.csv
    tdir = ROOT / "bot_trades" / item["bot_id"]
    tdir.mkdir(parents=True, exist_ok=True)
    with (tdir / "daily_pnl.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(item["daily_rows"][0].keys()))
        w.writeheader()
        w.writerows(item["daily_rows"])
    tfields = ["key", "kind", "strike", "setup", "entered", "exited", "quantity", "entry", "exit", "net_pnl", "charges", "reason"]
    with (tdir / "trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=tfields)
        w.writeheader()
        for t in eng.s["trades"]:
            w.writerow({k: t.get(k, "") for k in tfields})
    summ_clean = eng.summary()
    (tdir / "summary.json").write_text(json.dumps(summ_clean, indent=2), encoding="utf-8")

(ROOT / "qualified_20_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(f"\nSaved qualified_20_manifest.json with all {len(manifest)} competitors!")
