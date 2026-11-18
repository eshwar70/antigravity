#!/usr/bin/env python3
"""Systematic Generator & Optimizer: produces 20+ trading bots that strictly beat Winner 51
(> Rs +16,888.54 Net Profit) with >= 1.0 trade/day on the exact 54-session Rs 50,000 dataset.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import pickle
import sys
import time
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
BOTS_DIR = ROOT.parent / "bots"
FAST_STREAM_PATH = ROOT / "market_cache" / "fast_stream.pkl"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BOTS_DIR))

import bot_runtime
from bot_runtime import BASE_BOT_CONFIG, Blocked, CompetitionBotEngine
from qualify_bots import eval_one_spec, export_standalone_bot


def build_systematic_candidates() -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []

    # Common regime helpers
    def lv_reg(
        delta=0.65,
        stop_f=0.075,
        tgt_f=0.145,
        be_a=0.045,
        be_l=0.025,
        tr_a=0.065,
        tr_f=0.028,
        max_h=35,
        stall_m=11.0,
    ):
        return dict(
            enabled=True,
            vix_min=10.0,
            max_lots=1,
            target_delta=delta,
            delta_max=0.76,
            entry_end_clock="13:30",
            max_trades_day=1,
            max_hold_minutes=max_h,
            stop_fraction=stop_f,
            target_fraction=tgt_f,
            breakeven_activation_fraction=be_a,
            breakeven_lock_fraction=be_l,
            trail_activation_fraction=tr_a,
            trail_fraction=tr_f,
            max_premium_loss_fraction=0.45,
            early_stall_exit=True,
            stall_minutes=stall_m,
            step_trail_levels=[[0.085, 0.035], [0.15, 0.09], [0.22, 0.15], [0.28, 0.215]],
        )

    def cfg(
        *,
        lock=1650.0,
        risk=2600.0,
        loss=4000.0,
        lots=2,
        delta=0.60,
        dmin=0.40,
        dmax=0.68,
        trades=4,
        stop_f=0.10,
        tgt_f=0.34,
        be_a=0.065,
        be_l=0.028,
        tr_a=0.13,
        tr_f=0.05,
        steps=None,
        end_clk="14:00",
        hold=55,
        stall_vix=14.0,
        stall_m=11.0,
        lv=None,
    ):
        return dict(
            initial_wallet=50000.0,
            capital_floor=30000.0,
            safety_buffer=2000.0,
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
            stop_fraction=stop_f,
            target_fraction=tgt_f,
            breakeven_activation_fraction=be_a,
            breakeven_lock_fraction=be_l,
            trail_activation_fraction=tr_a,
            trail_fraction=tr_f,
            step_trail_levels=steps
            if steps is not None
            else [[0.085, 0.035], [0.15, 0.09], [0.22, 0.15], [0.28, 0.215]],
            entry_start_clock="09:20",
            entry_end_clock=end_clk,
            force_exit_clock="15:15",
            cooldown_minutes=5,
            direction_cooldown_minutes=15,
            max_hold_minutes=hold,
            max_premium_loss_fraction=0.48,
            vix_min=14.0,
            vix_max=35.0,
            early_stall_exit=False,
            early_stall_max_vix=stall_vix,
            stall_minutes=stall_m,
            low_vix_regime=lv if lv is not None else lv_reg(),
        )

    # 1. Kaufman Efficiency Pure-Flow Variations (Already beat Winner 51 at +20,937)
    for eff5_th, eff1_th, lock_v in [
        (0.28, 0.26, 1750.0),
        (0.30, 0.28, 1850.0),
        (0.30, 0.28, 2000.0),
        (0.32, 0.28, 1950.0),
        (0.32, 0.28, 2100.0),
        (0.30, 0.28, 2200.0),
        (0.34, 0.30, 2200.0),
        (0.34, 0.30, 2400.0),
        (0.34, 0.30, 2600.0),
    ]:
        tag = f"kaufman_flow_e{int(eff5_th*100)}_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"Kaufman Flow E{int(eff5_th*100)} Lock Rs{int(lock_v)}",
                family="Efficiency Ratio Filter",
                description=f"Dual-timeframe Kaufman efficiency (5m >= {eff5_th}, 1m >= {eff1_th}) with Rs {lock_v:.0f} daily profit lock.",
                config=cfg(lock=lock_v, risk=2800.0, tgt_f=0.38),
                signal_code=f'''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["eff_5m"] >= {eff5_th} and feat["eff10_1m"] >= {eff1_th} and feat["esep_5m"] >= 0.35:
        if feat["trend_5m"] == 1 and p > feat["e9"] > feat["e21"] and feat["roc3"] > 0.0004 and br != -1 and feat["rsi14"] <= 76.0:
            return 1, "KAUFMAN_L", None
        if feat["trend_5m"] == -1 and p < feat["e9"] < feat["e21"] and feat["roc3"] < -0.0004 and br != 1 and feat["rsi14"] >= 24.0:
            return -1, "KAUFMAN_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 2. Chandelier Trailing Runner Variations (Already beat Winner 51 at +18,425 to +65,560)
    for tgt_v, lock_v, st_trail in [
        (0.44, 1850.0, 0.050),
        (0.46, 2000.0, 0.050),
        (0.46, 2200.0, 0.052),
        (0.48, 2000.0, 0.052),
        (0.48, 2200.0, 0.052),
        (0.48, 2400.0, 0.052),
        (0.50, 2200.0, 0.055),
        (0.50, 2400.0, 0.055),
        (0.50, 2600.0, 0.055),
        (0.52, 2800.0, 0.058),
    ]:
        tag = f"chandelier_run_t{int(tgt_v*100)}_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"Chandelier Runner Tgt{int(tgt_v*100)}% Lock Rs{int(lock_v)}",
                family="Chandelier Wide-Target",
                description=f"5m Supertrend momentum runner with {int(tgt_v*100)}% target and Rs {lock_v:.0f} profit lock.",
                config=cfg(
                    lock=lock_v, risk=2800.0, tgt_f=tgt_v, tr_f=st_trail,
                    steps=[[0.085, 0.038], [0.15, 0.095], [0.23, 0.165], [0.32, 0.25], [0.42, 0.34]],
                    hold=65,
                ),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
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
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
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
''',
            )
        )

    # 3. Bollinger-Keltner Breakout with Profit Lock (Already beat Winner 51 at +17k to +46k)
    for lock_v in [1650.0, 1850.0, 2000.0, 2100.0, 2200.0, 2300.0, 2400.0, 2500.0]:
        tag = f"bb_keltner_lock_{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"Bollinger-Keltner Lock Rs{int(lock_v)}",
                family="Volatility Squeeze Breakout",
                description=f"Volatility band breakout with daily lock at Rs {lock_v:.0f}.",
                config=cfg(lock=lock_v, risk=2800.0, tgt_f=0.38),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and br != -1:
        if (p > feat["kc_up"] or p > feat["bb_up"]) and feat["macd_hist"] > 0 and feat["rsi14"] <= 76.0:
            return 1, "VOL_BAND_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and br != 1:
        if (p < feat["kc_dn"] or p < feat["bb_dn"]) and feat["macd_hist"] < 0 and feat["rsi14"] >= 24.0:
            return -1, "VOL_BAND_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 4. Asymmetric Tight-Stop Sniper with Profit Lock (Already beat Winner 51 at +22k to +35k)
    for lock_v in [1600.0, 1850.0, 2000.0, 2100.0, 2200.0, 2300.0, 2400.0, 2500.0]:
        tag = f"tight_stop_lock_{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"Asymmetric Tight-Stop Lock Rs{int(lock_v)}",
                family="Tight-Stop Asymmetric R:R",
                description=f"8% stop loss sniper with Rs {lock_v:.0f} daily profit lock.",
                config=cfg(
                    lock=lock_v, risk=2600.0, stop_f=0.08, tgt_f=0.36, be_a=0.055, be_l=0.025,
                    tr_a=0.11, tr_f=0.045, steps=[[0.075, 0.035], [0.135, 0.085], [0.21, 0.15], [0.29, 0.225]],
                ),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["st5m_dir"] == 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 74.0:
            return 1, "TIGHT_RR_L", None
    if feat["trend_5m"] == -1 and feat["st5m_dir"] == -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 26.0:
            return -1, "TIGHT_RR_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 5. Convex ATM-Gamma 50 Delta with Calibrated Locks (Already beat Winner 51 at +26k to +32k)
    for lock_v in [1850.0, 2000.0, 2200.0, 2400.0, 2600.0, 2800.0]:
        tag = f"gamma50_tuned_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"Convex Gamma-50 Tuned Lock Rs{int(lock_v)}",
                family="Convex Gamma Breakout",
                description=f"ATM 0.50 delta gamma convexity with Rs {lock_v:.0f} daily profit lock.",
                config=cfg(
                    lock=lock_v, risk=3000.0, delta=0.50, dmin=0.40, dmax=0.62,
                    stop_f=0.11, tgt_f=0.42, be_a=0.07, be_l=0.03, tr_a=0.13, tr_f=0.05,
                ),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and feat["roc3"] > 0.0004 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "GAMMA50_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and feat["roc3"] < -0.0004 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "GAMMA50_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 6. Winner-51 Parameter Upgrades (Already beat Winner 51 at +26k to +27k)
    for lock_v, tgt_f, end_clk in [
        (1650.0, 0.34, "14:00"),
        (1750.0, 0.35, "14:00"),
        (1850.0, 0.35, "14:00"),
        (1950.0, 0.35, "14:00"),
        (2000.0, 0.36, "14:10"),
        (2100.0, 0.36, "14:15"),
        (2200.0, 0.36, "14:15"),
    ]:
        tag = f"w51_boost_l{int(lock_v)}_t{int(tgt_f*100)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"WideRunner Boost Lock Rs{int(lock_v)} Tgt{int(tgt_f*100)}%",
                family="Asymmetric WideRunner",
                description=f"WideRunner with daily profit lock increased to Rs {lock_v:.0f} and target {int(tgt_f*100)}%.",
                config=cfg(lock=lock_v, risk=2800.0, tgt_f=tgt_f, end_clk=end_clk),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p, prev = feat["price"], feat["prev"]
    ups = (
        (1 if p > feat["e9"] > feat["e21"] else 0)
        + (1 if feat["macd"] > 0 and feat["macd_hist"] > 0 else 0)
        + (1 if feat["roc3"] > 0.0005 else 0)
        + (1 if p > feat["don10_hi"] else 0)
        + (1 if feat["e9"] > feat["e21"] and prev <= feat["prev_e9"] and p > feat["e9"] else 0)
        + (1 if (54.0 < feat["rsi14"] <= 75.0 and feat["rsi14"] > feat["rsi14_prev2"]) or (feat["rsi14_prev"] < 32.0 <= feat["rsi14"]) else 0)
    )
    dns = (
        (1 if p < feat["e9"] < feat["e21"] else 0)
        + (1 if feat["macd"] < 0 and feat["macd_hist"] < 0 else 0)
        + (1 if feat["roc3"] < -0.0005 else 0)
        + (1 if p < feat["don10_lo"] else 0)
        + (1 if feat["e9"] < feat["e21"] and prev >= feat["prev_e9"] and p < feat["e9"] else 0)
        + (1 if (25.0 <= feat["rsi14"] < 46.0 and feat["rsi14"] < feat["rsi14_prev2"]) or (feat["rsi14_prev"] > 68.0 >= feat["rsi14"]) else 0)
    )
    prop = 1 if (ups >= 2 and dns <= 1 and (ups - dns) >= 2) else (-1 if (dns >= 2 and ups <= 1 and (dns - ups) >= 2) else 0)
    if prop != 0 and feat["trend_5m"] == prop and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.40:
        eff_br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] == prop else feat["breadth_dir"]
        if eff_br != -prop and ((prop == 1 and feat["rsi14"] <= 75.0) or (prop == -1 and feat["rsi14"] >= 25.0)):
            if "12:15" <= feat["clock"] <= "13:05" and feat["vix"] >= 14.0 and not (feat["eff_5m"] >= 0.40 and eff_br == prop):
                return 0, "NONE", None
            return prop, "BOOST_1M", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 8. Fast-5m EMA5/13 Harvester with Profit Lock
    for lock_v in [1650.0, 1850.0, 2200.0]:
        tag = f"fast5m_harvester_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"Fast-5m Harvester Lock Rs{int(lock_v)}",
                family="Fast-5m Momentum",
                description=f"Fast 5m EMA(5,13) momentum with daily profit lock Rs {lock_v:.0f}.",
                config=cfg(lock=lock_v, risk=2800.0, tgt_f=0.38),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m_fast"] == 1 and feat["bias_15m"] == 1 and feat["esep_5m_fast"] >= 0.32 and feat["eff_5m"] >= 0.28:
        if p > feat["twap_day"] and p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br == 1 and feat["rsi14"] <= 75.0:
            return 1, "FAST5M_L", None
    if feat["trend_5m_fast"] == -1 and feat["bias_15m"] == -1 and feat["esep_5m_fast"] >= 0.32 and feat["eff_5m"] >= 0.28:
        if p < feat["twap_day"] and p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br == -1 and feat["rsi14"] >= 25.0:
            return -1, "FAST5M_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 9. Two-Shot & Multi-Shot High-Conviction Snipers with Refined Locks
    for lock_v, trades_n in [(2200.0, 2), (2600.0, 2), (2400.0, 3), (2800.0, 3)]:
        tag = f"shot_sniper_t{trades_n}_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"{trades_n}-Shot Sniper Lock Rs{int(lock_v)}",
                family="Surgical Conviction Sniper",
                description=f"Max {trades_n} surgical trades/day with Rs {lock_v:.0f} profit lock.",
                config=cfg(lock=lock_v, risk=3000.0, trades=trades_n, tgt_f=0.40),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and p > feat["twap_day"] and feat["macd_hist"] > 0 and br == 1 and feat["rsi14"] <= 75.0:
            return 1, "SHOT_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and p < feat["twap_day"] and feat["macd_hist"] < 0 and br == -1 and feat["rsi14"] >= 25.0:
            return -1, "SHOT_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 10. Whole-Session TWAP Reclaim Pro with Calibrated Locks
    for lock_v in [1650.0, 1950.0, 2300.0]:
        tag = f"twap_flow_tuned_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"TWAP Flow Tuned Lock Rs{int(lock_v)}",
                family="TWAP Institutional Flow",
                description=f"Cumulative TWAP institutional flow with Rs {lock_v:.0f} daily profit lock.",
                config=cfg(lock=lock_v, risk=2800.0, tgt_f=0.38),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p, tw = feat["price"], feat["twap_day"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if p > tw and feat["trend_5m"] == 1 and feat["bias_15m"] != -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "TWAP_FLOW_L", None
    if p < tw and feat["trend_5m"] == -1 and feat["bias_15m"] != 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "TWAP_FLOW_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 11. Convex ATM-Gamma 50 Delta with Calibrated Locks
    for lock_v in [1850.0, 2200.0, 2600.0]:
        tag = f"gamma50_tuned_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"Convex Gamma-50 Tuned Lock Rs{int(lock_v)}",
                family="Convex Gamma Breakout",
                description=f"ATM 0.50 delta gamma convexity with Rs {lock_v:.0f} daily profit lock.",
                config=cfg(
                    lock=lock_v, risk=3000.0, delta=0.50, dmin=0.40, dmax=0.62,
                    stop_f=0.11, tgt_f=0.42, be_a=0.07, be_l=0.03, tr_a=0.13, tr_f=0.05,
                ),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and feat["roc3"] > 0.0004 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "GAMMA50_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and feat["roc3"] < -0.0004 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "GAMMA50_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 12. Prior-Day Structure & ORB30 Tuned with Locks
    for lock_v in [1650.0, 1950.0]:
        tag = f"pdh_structure_tuned_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"PDH Structure Tuned Lock Rs{int(lock_v)}",
                family="Prior-Day Structure Breakout",
                description=f"Prior-Day High/Low structure with Rs {lock_v:.0f} daily profit lock.",
                config=cfg(lock=lock_v, risk=2800.0, tgt_f=0.38),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    pdh, pdl = feat["prev_high"], feat["prev_low"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and br != -1 and feat["rsi14"] <= 75.0:
        if (pdh is not None and p > pdh) or (feat["orb30_ready"] and p > feat["orb30_hi"]) or (p > feat["don20_hi"] and p > feat["twap_day"]):
            if p > feat["e9"] and feat["macd_hist"] > 0:
                return 1, "STRUCT_BRK_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and br != 1 and feat["rsi14"] >= 25.0:
        if (pdl is not None and p < pdl) or (feat["orb30_ready"] and p < feat["orb30_lo"]) or (p < feat["don20_lo"] and p < feat["twap_day"]):
            if p < feat["e9"] and feat["macd_hist"] < 0:
                return -1, "STRUCT_BRK_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 13. EMA Ribbon & ADX Power Tuned with Locks
    for lock_v in [1650.0, 1950.0]:
        tag = f"ribbon_adx_tuned_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"EMA Ribbon ADX Tuned Lock Rs{int(lock_v)}",
                family="EMA Ribbon + ADX",
                description=f"EMA Ribbon + ADX power trend with Rs {lock_v:.0f} daily lock.",
                config=cfg(lock=lock_v, risk=2800.0, tgt_f=0.38),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    bull = p > feat["e5"] > feat["e8"] > feat["e13"] > feat["e21"] and feat["e21"] > feat["e34"]
    bear = p < feat["e5"] < feat["e8"] < feat["e13"] < feat["e21"] and feat["e21"] < feat["e34"]
    if bull and feat["trend_5m"] == 1 and feat["adx_5m"] >= 16.0 and feat["pdi_5m"] > feat["mdi_5m"]:
        if feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "RIBBON_ADX_L", None
    if bear and feat["trend_5m"] == -1 and feat["adx_5m"] >= 16.0 and feat["mdi_5m"] > feat["pdi_5m"]:
        if feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "RIBBON_ADX_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 14. 5m RSI Surfer Tuned with Locks
    for lock_v in [1650.0, 1950.0]:
        tag = f"rsi5m_surfer_tuned_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"5m RSI Surfer Tuned Lock Rs{int(lock_v)}",
                family="MTF RSI Momentum",
                description=f"5m RSI regime surfing with Rs {lock_v:.0f} daily lock.",
                config=cfg(lock=lock_v, risk=2800.0, tgt_f=0.38),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["rsi_5m"] >= 57.0 and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "RSI5M_L", None
    if feat["rsi_5m"] <= 43.0 and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "RSI5M_S", None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    # 15. Dual-Session Morning & Afternoon Tuned with Locks
    for lock_v in [1650.0, 1950.0]:
        tag = f"dual_session_tuned_l{int(lock_v)}"
        specs.append(
            dict(
                slug=tag,
                bot_name=f"Dual-Session Tuned Lock Rs{int(lock_v)}",
                family="Session-Split Timing",
                description=f"Session-split timing with Rs {lock_v:.0f} daily lock.",
                config=cfg(lock=lock_v, risk=2800.0, tgt_f=0.38),
                signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    clk = feat["clock"]
    if "11:55" <= clk <= "13:05":
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, ("AM_EXP_L" if clk < "11:55" else "PM_POWER_L"), None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, ("AM_EXP_S" if clk < "11:55" else "PM_POWER_S"), None
    return 0, "NONE", None
''',
                exit_code='''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None
''',
            )
        )

    return specs


def main() -> None:
    specs = build_systematic_candidates()
    print(f"Generated {len(specs)} systematic candidate bot blueprints. Running qualification arena...", flush=True)

    from qualify_bots import run_qualification
    run_qualification(specs, export_top_20=True)


if __name__ == "__main__":
    main()
