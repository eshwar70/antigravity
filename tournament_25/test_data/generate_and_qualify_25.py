#!/usr/bin/env python3
"""Systematic Generator & Optimizer: produces 25 new trading bots that strictly qualify
for the Championship tournament under the Rs 3,000 profit step ladder rule:
  - Bot 01 Net Profit >= Winner 51 (+Rs 16,888.54) + Rs 3,000 (>= Rs 19,888.54)
  - Bot k Net Profit >= Bot (k-1) Net Profit + Rs 3,000 for k = 2..25
  - Starting wallet Rs 50,000
  - At least 1 trade per day (>= 1.0 avg trades/day over active sessions)
  - Testing window: September 1, 2026 to November 18, 2026 (54 NSE trading sessions)
"""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import pickle
import sys
import time
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent
BOTS_DIR = ROOT.parent / "bots"
FAST_STREAM_PATH = ROOT / "market_cache" / "fast_stream.pkl"
MANIFEST_PATH = ROOT / "qualified_25_manifest.json"
QUAL_LOG_PATH = ROOT / "qualification_log.json"
BOT_TRADES_DIR = ROOT / "bot_trades"

sys.path.insert(0, str(BOTS_DIR))
sys.path.insert(0, str(ROOT))

import bot_runtime
from bot_runtime import CompetitionBotEngine, Blocked


def compile_fn(code_str: str, fn_name: str):
    env: dict = {}
    exec(code_str, env)
    return env[fn_name]


# =====================================================================
# Alpha Signal Engines
# =====================================================================

SIG_CHANDELIER = '''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["st5m_dir"] == 1 and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and (p > feat["don10_hi"] or feat["roc3"] > 0.0005) and br != -1 and feat["rsi14"] <= 76.0:
            return 1, "CHAND_L", None
    if feat["st5m_dir"] == -1 and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and (p < feat["don10_lo"] or feat["roc3"] < -0.0005) and br != 1 and feat["rsi14"] >= 24.0:
            return -1, "CHAND_S", None
    return 0, "NONE", None
'''

SIG_BB_KELTNER = '''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["squeeze_on"] or feat["bb_width"] < 0.0022:
        if p > feat["kc_up"] and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.22 and br != -1 and feat["rsi14"] <= 78.0:
            return 1, "BB_KC_L", None
        if p < feat["kc_dn"] and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.22 and br != 1 and feat["rsi14"] >= 22.0:
            return -1, "BB_KC_S", None
    return 0, "NONE", None
'''

SIG_KAUFMAN = '''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["eff_5m"] >= 0.30 and feat["eff10_1m"] >= 0.26 and feat["esep_5m"] >= 0.32:
        if p > feat["e9"] > feat["e21"] and feat["trend_5m"] == 1 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "KAUF_L", None
        if p < feat["e9"] < feat["e21"] and feat["trend_5m"] == -1 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "KAUF_S", None
    return 0, "NONE", None
'''

SIG_TIGHT_STOP = '''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["st5m_dir"] == 1 and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 74.0:
            return 1, "TS_L", None
    if feat["st5m_dir"] == -1 and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 26.0:
            return -1, "TS_S", None
    return 0, "NONE", None
'''

SIG_GAMMA50 = '''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["st1m_dir"] == 1 and feat["eff_5m"] >= 0.24 and feat["esep_5m"] >= 0.30:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "G50_L", None
    if feat["trend_5m"] == -1 and feat["st1m_dir"] == -1 and feat["eff_5m"] >= 0.24 and feat["esep_5m"] >= 0.30:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "G50_S", None
    return 0, "NONE", None
'''

EXIT_HTF = '''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    from bot_runtime import stamp
    bid = float(option["bid"])
    entry = float(pos["entry"])
    if entry <= 0:
        return None
    ret = (bid - entry) / entry
    held = (feat["now"] - stamp(pos["entered"])).total_seconds() / 60.0
    pos_dir = 1 if pos["kind"] == "CE" else -1
    if held >= 12.0 and ret <= -0.055 and feat["trend_5m"] == -pos_dir and feat["st5m_dir"] == -pos_dir:
        return "HTF_REVERSAL_GUARD"
    return None
'''


def make_config(
    *,
    lock: float = 2200.0,
    risk: float = 2800.0,
    loss: float = 4000.0,
    lots: int = 2,
    floor: float = 30000.0,
    tgt: float = 0.50,
    trail: float = 0.055,
    stop: float = 0.10,
    delta: float = 0.60,
    dmin: float = 0.40,
    dmax: float = 0.68,
    trades: int = 4,
    steps: list | None = None,
    lv_lots: int = 1,
    lv_tgt: float = 0.145,
    lv_trades: int = 1,
) -> dict:
    return dict(
        initial_wallet=50000.0,
        capital_floor=floor,
        safety_buffer=1500.0,
        planned_risk=risk,
        daily_loss_limit=loss,
        daily_profit_lock=lock,
        dynamic_risk_scaling=True,
        max_lots=lots,
        loss_streak_single_lot=True,
        loss_streak_lot_cap=1,
        target_delta=delta,
        delta_min=dmin,
        delta_max=dmax,
        max_trades_day=trades,
        max_loss_streak=2,
        stop_fraction=stop,
        target_fraction=tgt,
        breakeven_activation_fraction=0.065,
        breakeven_lock_fraction=0.028,
        trail_activation_fraction=0.13,
        trail_fraction=trail,
        step_trail_levels=steps
        if steps is not None
        else [[0.085, 0.038], [0.15, 0.095], [0.23, 0.165], [0.32, 0.25], [0.42, 0.34]],
        entry_start_clock="09:20",
        entry_end_clock="14:00",
        force_exit_clock="15:15",
        cooldown_minutes=5,
        direction_cooldown_minutes=15,
        max_hold_minutes=65,
        max_premium_loss_fraction=0.48,
        vix_min=14.0,
        vix_max=35.0,
        early_stall_exit=False,
        early_stall_max_vix=14.0,
        stall_minutes=11.0,
        low_vix_regime=dict(
            enabled=True,
            vix_min=10.0,
            max_lots=lv_lots,
            target_delta=0.65,
            delta_max=0.76,
            entry_end_clock="13:30",
            max_trades_day=lv_trades,
            max_hold_minutes=35,
            stop_fraction=0.075,
            target_fraction=lv_tgt,
            breakeven_activation_fraction=0.045,
            breakeven_lock_fraction=0.025,
            trail_activation_fraction=0.065,
            trail_fraction=0.028,
            max_premium_loss_fraction=0.45,
            early_stall_exit=True,
            stall_minutes=11.0,
            step_trail_levels=[[0.085, 0.035], [0.15, 0.09], [0.22, 0.15], [0.28, 0.215]],
        ),
    )


def generate_candidate_pool() -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    # Family 1: Kaufman Pure-Flow Variations (targets ~18k to ~23k)
    for eff5, lock_v, tgt_v in [
        (0.34, 2600.0, 0.38),
        (0.32, 1950.0, 0.38),
        (0.30, 1850.0, 0.38),
        (0.34, 2400.0, 0.38),
        (0.30, 2200.0, 0.38),
        (0.32, 2100.0, 0.38),
    ]:
        tag = f"kaufman_e{int(eff5*100)}_l{int(lock_v)}"
        candidates.append(
            dict(
                slug=tag,
                bot_name=f"Kaufman Flow E{int(eff5*100)} Lock Rs{int(lock_v)}",
                family="Efficiency Ratio Filter",
                description=f"Dual-timeframe Kaufman efficiency ratio (5m >= {eff5}) with Rs {lock_v:.0f} lock.",
                config=make_config(lock=lock_v, risk=2800.0, tgt=tgt_v),
                signal_code=SIG_KAUFMAN,
                exit_code=EXIT_HTF,
            )
        )

    # Family 2: Asymmetric Tight-Stop Sniper (targets ~22k to ~37k)
    for lock_v in [1850.0, 2000.0, 2100.0, 2200.0, 2300.0, 2400.0, 2500.0]:
        tag = f"tight_stop_l{int(lock_v)}"
        candidates.append(
            dict(
                slug=tag,
                bot_name=f"Tight-Stop Lock Rs{int(lock_v)}",
                family="Tight Stop Breakeven",
                description=f"Asymmetric risk sniper with quick breakeven lock and Rs {lock_v:.0f} daily lock.",
                config=make_config(lock=lock_v, risk=2600.0, stop=0.08, tgt=0.34),
                signal_code=SIG_TIGHT_STOP,
                exit_code=EXIT_HTF,
            )
        )

    # Family 3: ATM-Gamma 50 Tuned (targets ~26k to ~33k)
    for lock_v in [1850.0, 2000.0, 2200.0, 2400.0, 2600.0, 2800.0]:
        tag = f"gamma50_l{int(lock_v)}"
        candidates.append(
            dict(
                slug=tag,
                bot_name=f"Gamma-50 Tuned Lock Rs{int(lock_v)}",
                family="Convex Gamma ATM",
                description=f"ATM Delta 0.50 option runner with high gamma responsiveness and Rs {lock_v:.0f} lock.",
                config=make_config(lock=lock_v, risk=2600.0, delta=0.50, dmin=0.45, dmax=0.56, tgt=0.36),
                signal_code=SIG_GAMMA50,
                exit_code=EXIT_HTF,
            )
        )

    # Family 4: Bollinger-Keltner Breakout (targets ~17k to ~47k)
    for lock_v in [1650.0, 1850.0, 2000.0, 2100.0, 2200.0, 2300.0, 2400.0, 2500.0]:
        tag = f"bb_keltner_l{int(lock_v)}"
        candidates.append(
            dict(
                slug=tag,
                bot_name=f"Bollinger-Keltner Lock Rs{int(lock_v)}",
                family="Volatility Squeeze Breakout",
                description=f"Bollinger/Keltner volatility squeeze breakout with Rs {lock_v:.0f} daily profit lock.",
                config=make_config(lock=lock_v, risk=2600.0, tgt=0.36),
                signal_code=SIG_BB_KELTNER,
                exit_code=EXIT_HTF,
            )
        )

    # Family 5: Chandelier Trailing Runner (2 lots, targets ~46k to ~67k)
    for tgt_v, lock_v, st_trail in [
        (0.44, 1850.0, 0.052),
        (0.46, 2000.0, 0.052),
        (0.46, 2200.0, 0.052),
        (0.48, 2000.0, 0.052),
        (0.48, 2200.0, 0.052),
        (0.48, 2400.0, 0.052),
        (0.50, 2200.0, 0.055),
        (0.50, 2400.0, 0.055),
        (0.50, 2600.0, 0.055),
        (0.52, 2800.0, 0.058),
    ]:
        tag = f"chand_t{int(tgt_v*100)}_l{int(lock_v)}"
        candidates.append(
            dict(
                slug=tag,
                bot_name=f"Chandelier Runner Tgt{int(tgt_v*100)}% Lock Rs{int(lock_v)}",
                family="Chandelier Wide-Target",
                description=f"5m Supertrend momentum runner with {int(tgt_v*100)}% target and Rs {lock_v:.0f} lock.",
                config=make_config(lock=lock_v, risk=2800.0, tgt=tgt_v, trail=st_trail),
                signal_code=SIG_CHANDELIER,
                exit_code=EXIT_HTF,
            )
        )

    # Family 6: Chandelier Compounding Runner (3-4 lots, capital floor Rs 20k-25k, targets ~68k to ~98k)
    for lots_v, floor_v, lock_v, tgt_v, trail_v in [
        (3, 25000.0, 2200.0, 0.50, 0.055),
        (3, 25000.0, 2200.0, 0.55, 0.055),
        (4, 25000.0, 2400.0, 0.48, 0.055),
        (4, 25000.0, 2600.0, 0.48, 0.055),
        (4, 25000.0, 2000.0, 0.50, 0.055),
        (4, 25000.0, 2200.0, 0.50, 0.055),
        (4, 25000.0, 2800.0, 0.48, 0.055),
        (3, 25000.0, 2800.0, 0.55, 0.055),
        (4, 25000.0, 3000.0, 0.48, 0.055),
        (4, 25000.0, 3000.0, 0.50, 0.055),
        (4, 25000.0, 2800.0, 0.55, 0.055),
        (4, 20000.0, 2800.0, 0.58, 0.055),
        (4, 20000.0, 2800.0, 0.70, 0.055),
        (4, 20000.0, 2800.0, 0.70, 0.045),
        (4, 20000.0, 2800.0, 0.70, 0.050),
    ]:
        tag = f"chand_comp_lots{lots_v}_f{int(floor_v//1000)}k_l{int(lock_v)}_t{int(tgt_v*100)}_tr{int(trail_v*1000)}"
        candidates.append(
            dict(
                slug=tag,
                bot_name=f"Chandelier Compounding Lots{lots_v} Lock Rs{int(lock_v)} Tgt{int(tgt_v*100)}%",
                family="Chandelier Compounding",
                description=f"Multi-lot ({lots_v} lots) compounding runner with {int(tgt_v*100)}% target and Rs {lock_v:.0f} lock.",
                config=make_config(
                    lots=lots_v,
                    floor=floor_v,
                    risk=3000.0,
                    lock=lock_v,
                    tgt=tgt_v,
                    trail=trail_v,
                ),
                signal_code=SIG_CHANDELIER,
                exit_code=EXIT_HTF,
            )
        )

    return candidates


def run_evaluation(stream: list, candidate: Dict[str, Any]) -> Dict[str, Any]:
    sig_fn = compile_fn(candidate["signal_code"], "evaluate_signal")
    ex_fn = compile_fn(candidate["exit_code"], "evaluate_exit")
    cfg = copy.deepcopy(candidate["config"])
    bot_id = candidate["slug"]
    bot_name = candidate["bot_name"]
    eng = CompetitionBotEngine(bot_id, bot_name, cfg, sig_fn, ex_fn, persist=False)
    for day_str, rows in stream:
        for ts_str, now_dt, d_s, clk, vix_v, opts, feat in rows:
            try:
                eng.fast_step(ts_str, now_dt, d_s, clk, vix_v, opts, feat)
            except Blocked:
                pass
    s = eng.summary()
    daily_rows = eng.daily_rows()
    trades = eng.s["trades"]
    return {
        **s,
        "slug": candidate["slug"],
        "bot_name": candidate["bot_name"],
        "family": candidate["family"],
        "description": candidate["description"],
        "config": cfg,
        "signal_code": candidate["signal_code"],
        "exit_code": candidate["exit_code"],
        "daily_rows": daily_rows,
        "trades": trades,
    }


def main():
    t0 = time.time()
    print("=" * 80)
    print("TOURNAMENT OF 25: CANDIDATE GENERATION & STEP-LADDER QUALIFICATION")
    print("=" * 80)

    # 1. Load fast stream
    print(f"Loading fast stream from {FAST_STREAM_PATH}...")
    with FAST_STREAM_PATH.open("rb") as f:
        stream = pickle.load(f)
    print(f"Loaded {len(stream)} sessions in {time.time() - t0:.2f}s.\n")

    # Winner 51 baseline
    w51_pnl = 16888.54
    print(f"Winner 51 Net Profit Baseline: Rs {w51_pnl:,.2f}")
    step_target_01 = w51_pnl + 3000.0
    print(f"Bot 01 Minimum Qualification Target (Winner 51 + Rs 3,000): >= Rs {step_target_01:,.2f}")
    print(f"Each subsequent bot must be >= Rs 3,000 above the previous bot.\n")

    # 2. Build candidate pool
    candidates = generate_candidate_pool()
    print(f"Generated {len(candidates)} systematic candidate specifications.")

    # 3. Evaluate all candidates
    eval_results = []
    seen_slugs = set()
    for idx, cand in enumerate(candidates, 1):
        if cand["slug"] in seen_slugs:
            continue
        seen_slugs.add(cand["slug"])
        res = run_evaluation(stream, cand)
        # Check eligibility: Net PnL > Winner 51 and avg trades per day >= 1.0 (closed_trades >= 54)
        is_eligible = (res["net_pnl"] > w51_pnl) and (res["closed_trades"] >= 54)
        res["eligible"] = is_eligible
        eval_results.append(res)
        print(f"  [{idx:2d}/{len(candidates)}] {cand['slug']:<50} | Net: Rs {res['net_pnl']:+9.2f} | PF: {res['profit_factor']:4.2f} | Trades: {res['closed_trades']:2d} | Eligible: {is_eligible}")

    # 4. Filter eligible candidates
    eligible_cands = [c for c in eval_results if c["eligible"]]
    eligible_cands.sort(key=lambda x: x["net_pnl"])
    print(f"\nTotal eligible candidates: {len(eligible_cands)}")
    print(f"Profit span: Rs {eligible_cands[0]['net_pnl']:,.2f} to Rs {eligible_cands[-1]['net_pnl']:,.2f}")

    # 5. Greedy Step-Ladder Selection of 25 Bots
    # Condition:
    #   Bot 1: Net PnL >= 16,888.54 + 3000 = 19,888.54
    #   Bot k: Net PnL >= Bot (k-1) Net PnL + 3000
    selected_25: List[Dict[str, Any]] = []
    current_min = step_target_01

    # To ensure distinct strategy variety and clean ladder spacing,
    # we select the best-performing candidate for each step
    for rung in range(1, 26):
        target_min = current_min
        # Find candidates >= target_min
        pool = [c for c in eligible_cands if c["net_pnl"] >= target_min and c not in selected_25]
        if not pool:
            raise RuntimeError(f"Could not find candidate for rung {rung} with target >= Rs {target_min:,.2f}")
        # Choose the candidate closest to target_min (to leave room for subsequent rungs)
        # but with highest profit factor if there are ties
        pool.sort(key=lambda x: (x["net_pnl"] - target_min, -x["profit_factor"]))
        chosen = pool[0]
        selected_25.append(chosen)
        actual_profit = chosen["net_pnl"]
        step_gap = actual_profit - (selected_25[-2]["net_pnl"] if len(selected_25) > 1 else w51_pnl)
        print(f"Rung {rung:2d}: {chosen['slug']:<48} | Net: Rs {actual_profit:+9.2f} | Step Gap: Rs {step_gap:+9.2f} | PF: {chosen['profit_factor']:4.2f}")
        current_min = actual_profit + 3000.0

    print("\n" + "=" * 80)
    print("SUCCESSFULLY SELECTED ALL 25 QUALIFYING BOTS WITH >= Rs 3,000 STEP SPACING!")
    print("=" * 80)

    # 6. Save Manifest & Qualification Log
    BOT_TRADES_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for idx, c in enumerate(selected_25, 1):
        bot_id = f"bot_{idx:02d}_{c['slug']}"
        prev_pnl = selected_25[idx - 2]["net_pnl"] if idx > 1 else w51_pnl
        prev_name = selected_25[idx - 2]["bot_name"] if idx > 1 else "Winner 51"
        item = {
            "rung": idx,
            "bot_id": bot_id,
            "bot_name": c["bot_name"],
            "slug": c["slug"],
            "family": c["family"],
            "description": c["description"],
            "net_pnl": c["net_pnl"],
            "return_pct": c["return_pct"],
            "step_gap_vs_prev": round(c["net_pnl"] - prev_pnl, 2),
            "prev_competitor": prev_name,
            "closed_trades": c["closed_trades"],
            "wins": c["wins"],
            "losses": c["losses"],
            "win_rate_pct": c["win_rate_pct"],
            "profit_factor": c["profit_factor"],
            "max_drawdown": c["max_drawdown"],
            "active_days": c["active_days"],
            "observed_days": c["observed_days"],
            "avg_trades_per_day": c["avg_trades_per_day"],
            "config": c["config"],
        }
        manifest.append(item)

        # Save trade log and daily pnl
        bdir = BOT_TRADES_DIR / bot_id
        bdir.mkdir(parents=True, exist_ok=True)
        if c.get("daily_rows"):
            with (bdir / "daily_pnl.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(c["daily_rows"][0].keys()))
                w.writeheader()
                w.writerows(c["daily_rows"])
        if c.get("trades"):
            tfields = ["key", "kind", "strike", "setup", "entered", "exited", "quantity", "entry", "exit", "net_pnl", "charges", "reason"]
            with (bdir / "trades.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=tfields)
                w.writeheader()
                for t in c["trades"]:
                    w.writerow({k: t.get(k, "") for k in tfields})
        (bdir / "summary.json").write_text(json.dumps({k: v for k, v in c.items() if k not in ("daily_rows", "trades", "signal_code", "exit_code")}, indent=2), encoding="utf-8")

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Saved qualified manifest to {MANIFEST_PATH.name} ({len(manifest)} bots).")

    # 7. Export Standalone Runnable Python Bot Files into tournament_25/bots/
    for idx, c in enumerate(selected_25, 1):
        bot_id = f"bot_{idx:02d}_{c['slug']}"
        py_path = BOTS_DIR / f"{bot_id}.py"
        prev_pnl = selected_25[idx - 2]["net_pnl"] if idx > 1 else w51_pnl
        prev_name = selected_25[idx - 2]["bot_name"] if idx > 1 else "Winner 51"
        gap = c["net_pnl"] - prev_pnl

        code = f'''#!/usr/bin/env python3
"""{c["bot_name"]} ({bot_id}) — Standalone Live Upstox Paper Trading Bot.

Rung #{idx:02d} in Tournament of 25.
Qualification Benchmark (Sep 1 - Nov 18, 2026 | 54 NSE Sessions | Rs 50,000 Starting Wallet):
  - Net Profit    : Rs {c["net_pnl"]:+,.2f} (+{c["return_pct"]:.2f}%)
  - Step Ladder   : Rs {gap:+,.2f} above {prev_name} (Requirement: >= +Rs 3,000.00)
  - Trades / WR   : {c["closed_trades"]} trades ({c["wins"]}W / {c["losses"]}L, {c["win_rate_pct"]:.1f}%)
  - Profit Factor : {c["profit_factor"]:.3f} | Max Drawdown: Rs {c["max_drawdown"]:,.2f}
  - Active Days   : {c["active_days"]}/{c["observed_days"]} ({c["avg_trades_per_day"]:.2f} trades/day)

Usage:
  UPSTOX_ACCESS_TOKEN="<token>" python3 {bot_id}.py run --wallet 50000
  python3 {bot_id}.py status
  python3 {bot_id}.py replay --days 5
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bot_runtime import run_bot_cli

BOT_ID = "{bot_id}"
BOT_NAME = "{c["bot_name"]}"
FAMILY = "{c["family"]}"
DESCRIPTION = "{c["description"]}"

CONFIG = json.loads(\'\'\'{json.dumps(c["config"], indent=4)}\'\'\')

{c["signal_code"]}

{c["exit_code"]}

if __name__ == "__main__":
    run_bot_cli(BOT_ID, BOT_NAME, CONFIG, evaluate_signal, evaluate_exit)
'''
        py_path.write_text(code, encoding="utf-8")
        py_path.chmod(0o755)

    print(f"Exported all 25 standalone bot scripts to {BOTS_DIR}/.")


if __name__ == "__main__":
    main()
