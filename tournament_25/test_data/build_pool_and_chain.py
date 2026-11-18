#!/usr/bin/env python3
"""Exact DP Longest Chain Finder & Gap Filler for 25-Bot Step Ladder."""
import copy
import json
from pathlib import Path
import pickle
import sys
import time

ROOT = Path("test/test_data")
BOTS = Path("test/bots")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BOTS))

from generate_and_qualify import build_systematic_candidates
from qualify_bots import _compile_fn
import bot_runtime
from bot_runtime import CompetitionBotEngine, Blocked

CACHE_FILE = Path("tournament_25/test_data/candidate_cache.pkl")
FAST_STREAM_PATH = ROOT / "market_cache" / "fast_stream.pkl"

pool_by_slug = {}
if CACHE_FILE.exists():
    try:
        with open(CACHE_FILE, "rb") as f:
            pool_by_slug = pickle.load(f)
        print(f"Loaded {len(pool_by_slug)} cached candidates from {CACHE_FILE}")
    except Exception as e:
        print(f"Failed to load cache: {e}")

with FAST_STREAM_PATH.open("rb") as f:
    stream = pickle.load(f)

specs = {s["slug"]: s for s in build_systematic_candidates()}
q = json.loads((ROOT / "qualification_log.json").read_text(encoding="utf-8"))

cand_chand = specs["chandelier_run_t50_l2200"]
cand_tight = specs["tight_stop_lock_2300"]
cand_w51 = [c for c in build_systematic_candidates() if "w51_boost" in c["slug"]][0]

SIG_CHAND = cand_chand["signal_code"]
EXIT_HTF = cand_chand["exit_code"]

# Seed base candidates
for c in q["candidates"]:
    if c["eligible"] and c["slug"] in specs and c["slug"] not in pool_by_slug:
        sp = specs[c["slug"]]
        pool_by_slug[c["slug"]] = {
            "slug": c["slug"],
            "bot_name": c["bot_name"],
            "family": c["family"],
            "description": c["description"],
            "config": sp["config"],
            "signal_code": sp["signal_code"],
            "exit_code": sp["exit_code"],
            "net_pnl": c["net_pnl"],
            "profit_factor": c["profit_factor"],
            "closed_trades": c["closed_trades"],
            "wins": c["wins"],
            "losses": c["losses"],
            "win_rate_pct": c["win_rate_pct"],
            "max_drawdown": c["max_drawdown"],
            "active_days": c["active_days"],
            "observed_days": c["observed_days"],
            "avg_trades_per_day": c["avg_trades_per_day"],
            "return_pct": c.get("return_pct", round(c["net_pnl"] / 50000.0 * 100.0, 2)),
        }

# Systematic variations
variations = []

# Range 20k to 35k
for lock in [1400, 1550, 1700, 1850, 2000, 2100]:
    for tgt in [0.28, 0.30, 0.32, 0.34, 0.35]:
        variations.append((
            f"w51_l{lock}_t{int(tgt*100)}",
            f"WideRunner Boost L{lock} T{int(tgt*100)}%",
            "Asymmetric WideRunner",
            2, 30000.0, 2800.0, float(lock), tgt, 0.050,
            cand_w51["signal_code"], cand_w51["exit_code"]
        ))

# Range 30k to 65k (dense grid across target & lock)
for lock in [1400, 1600, 1700, 1800, 1900, 2000, 2100, 2200, 2300, 2400, 2600, 2800]:
    for tgt in [0.28, 0.30, 0.32, 0.34, 0.36, 0.38, 0.40, 0.42, 0.44, 0.46, 0.48, 0.50, 0.52]:
        variations.append((
            f"chand_2l_l{lock}_t{int(tgt*100)}",
            f"Chandelier 2L L{lock} T{int(tgt*100)}%",
            "Chandelier Target Scaler",
            2, 30000.0, 2800.0, float(lock), tgt, 0.055,
            SIG_CHAND, EXIT_HTF
        ))

# Range 35k to 55k: Tight stop variations
for lock in [2100, 2300, 2400, 2500, 2650, 2800, 3000]:
    for tgt in [0.32, 0.34, 0.36, 0.38, 0.40, 0.42]:
        variations.append((
            f"tight_l{lock}_t{int(tgt*100)}",
            f"Tight-Stop L{lock} T{int(tgt*100)}%",
            "Tight-Stop Asymmetric R:R",
            2, 30000.0, 2600.0, float(lock), tgt, 0.045,
            cand_tight["signal_code"], cand_tight["exit_code"]
        ))

# Range 65k to 95k: Chandelier 3-lot compounding
for floor in [20000.0, 22500.0, 25000.0]:
    for lock in [2000, 2200, 2400, 2600, 2800, 3000]:
        for tgt in [0.48, 0.52, 0.55, 0.58, 0.60, 0.65, 0.70]:
            for trail in [0.048, 0.052, 0.055]:
                variations.append((
                    f"chand_3l_f{int(floor//1000)}k_l{lock}_t{int(tgt*100)}_tr{int(trail*1000)}",
                    f"Chandelier 3L F{int(floor//1000)}k L{lock} T{int(tgt*100)}%",
                    "Chandelier Compounding 3L",
                    3, floor, 2800.0, float(lock), tgt, trail,
                    SIG_CHAND, EXIT_HTF
                ))

# Range 80k to 125k: Chandelier 4-lot compounding
for floor in [18000.0, 20000.0, 22500.0, 25000.0]:
    for lock in [2200, 2500, 2800, 3000, 3200, 3500]:
        for tgt in [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
            for trail in [0.045, 0.050, 0.055]:
                variations.append((
                    f"chand_4l_f{int(floor//1000)}k_l{lock}_t{int(tgt*100)}_tr{int(trail*1000)}",
                    f"Chandelier 4L F{int(floor//1000)}k L{lock} T{int(tgt*100)}%",
                    "Chandelier Compounding 4L",
                    4, floor, 3000.0, float(lock), tgt, trail,
                    SIG_CHAND, EXIT_HTF
                ))

# Higher tier 5-lot compounding for 100k-140k
for floor in [18000.0, 20000.0]:
    for lock in [2800, 3200, 3500]:
        for tgt in [0.65, 0.70, 0.75, 0.80]:
            variations.append((
                f"chand_5l_f{int(floor//1000)}k_l{lock}_t{int(tgt*100)}",
                f"Chandelier 5L F{int(floor//1000)}k L{lock} T{int(tgt*100)}%",
                "Chandelier Compounding 5L",
                5, floor, 3200.0, float(lock), tgt, 0.050,
                SIG_CHAND, EXIT_HTF
            ))

print(f"Total variations in search space: {len(variations)}")

sig_cache = {}
def get_fns(sc, ec):
    k = (sc, ec)
    if k not in sig_cache:
        sig_cache[k] = (_compile_fn(sc, "evaluate_signal"), _compile_fn(ec, "evaluate_exit"))
    return sig_cache[k]

tested_new = 0
t0 = time.time()
for slug, name, fam, lots, floor, risk, lock, tgt, trail, sc, ec in variations:
    if slug in pool_by_slug:
        continue
    tested_new += 1

    cfg = dict(cand_chand["config"] if "chand" in slug else (cand_tight["config"] if "tight" in slug else cand_w51["config"]))
    cfg.update(max_lots=lots, capital_floor=floor, planned_risk=risk, daily_profit_lock=lock, target_fraction=tgt, trail_fraction=trail)
    
    sig_fn, ex_fn = get_fns(sc, ec)
    eng = CompetitionBotEngine(slug, name, {**bot_runtime.BASE_BOT_CONFIG, **cfg, "initial_wallet": 50000.0}, sig_fn, ex_fn, persist=False)
    for day_str, rows in stream:
        for ts_str, now_dt, d_s, clk, vix_v, opts, feat in rows:
            try:
                eng.fast_step(ts_str, now_dt, d_s, clk, vix_v, opts, feat)
            except Blocked:
                pass
    s = eng.summary()
    if s["net_pnl"] > 16888.54 and s["closed_trades"] >= 54:
        pool_by_slug[slug] = {
            "slug": slug,
            "bot_name": name,
            "family": fam,
            "description": f"{fam} with {lots} lots, lock Rs {lock:.0f}, target {tgt*100:.0f}%, trail {trail*100:.1f}%.",
            "config": cfg,
            "signal_code": sc,
            "exit_code": ec,
            **s,
        }

    if tested_new % 50 == 0:
        print(f"  Evaluated {tested_new} new candidates ({time.time() - t0:.1f}s) | Total valid: {len(pool_by_slug)}")
        # Periodically persist cache
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(pool_by_slug, f)

with open(CACHE_FILE, "wb") as f:
    pickle.dump(pool_by_slug, f)
print(f"Total pool size saved: {len(pool_by_slug)}")

# Filter candidates >= 19,888.54
valid = sorted([v for v in pool_by_slug.values() if v["net_pnl"] >= 16888.54 + 3000.0], key=lambda x: x["net_pnl"])
print(f"Eligible candidates >= Rs 19,888.54: {len(valid)}")
print(f"Span: Rs {valid[0]['net_pnl']:,.2f} to Rs {valid[-1]['net_pnl']:,.2f}")

# Exact DP Longest Path
N = len(valid)
dp = [1] * N
prev = [-1] * N

for i in range(N):
    for j in range(i + 1, N):
        if valid[j]["net_pnl"] >= valid[i]["net_pnl"] + 3000.0:
            if dp[i] + 1 > dp[j]:
                dp[j] = dp[i] + 1
                prev[j] = i

max_len = max(dp)
best_end = dp.index(max_len)
print(f"EXACT MATHEMATICAL LONGEST STEP-LADDER CHAIN LENGTH: {max_len} rungs!")

# Reconstruct longest chain
curr = best_end
longest_chain = []
while curr != -1:
    longest_chain.append(valid[curr])
    curr = prev[curr]
longest_chain.reverse()

print(f"Chain span: Rs {longest_chain[0]['net_pnl']:,.2f} to Rs {longest_chain[-1]['net_pnl']:,.2f}")

if max_len >= 25:
    # If longer than 25, we can select exactly 25 rungs!
    # For example, select 25 evenly spaced rungs or the first 25
    # Let's verify any subset of 25 rungs has step >= 3000:
    # Any subsequence of a valid chain naturally has step >= 3000!
    # If we take 25 rungs from a chain of length >= 25, every step is still >= 3000!
    # Let's take the first 25 or evenly spaced 25:
    selected_25 = longest_chain[:25]
    print("\n" + "=" * 90)
    print("SUCCESS! SELECTED EXACT 25 QUALIFYING BOTS:")
    print("=" * 90)
    w51 = 16888.54
    p = w51
    for idx, b in enumerate(selected_25, 1):
        gap = b["net_pnl"] - p
        assert gap >= 3000.0, f"Gap violation on rung {idx}: {gap}"
        print(f"Rung {idx:02d}: {b['slug']:<45} | Net: Rs {b['net_pnl']:+9.2f} | Gap: Rs {gap:+8.2f} | PF: {b['profit_factor']:4.2f} | Trades: {b['closed_trades']}")
        p = b["net_pnl"]

    # Save to ladder_25_cache.pkl
    out_path = Path("tournament_25/test_data/ladder_25_cache.pkl")
    with open(out_path, "wb") as f:
        pickle.dump({"pool": list(pool_by_slug.values()), "chain": selected_25}, f)
    print(f"\nSaved 25-bot ladder to {out_path}!")
else:
    print(f"Need 25 rungs, but longest chain is {max_len}.")
    # Print the gaps in the longest chain
    p = 16888.54
    for idx, b in enumerate(longest_chain, 1):
        gap = b["net_pnl"] - p
        print(f"  Rung {idx:02d}: {b['slug']} | Net: Rs {b['net_pnl']:+9.2f} | Gap: Rs {gap:+8.2f}")
        p = b["net_pnl"]
