#!/usr/bin/env python3
"""Bollinger-Keltner Lock Rs2100 (bot_11_bb_keltner_lock_2100) — Live Upstox Paper Trading Bot.

Family      : Volatility Squeeze Breakout
Description : Volatility band breakout with daily lock at Rs 2100.
Qualification Benchmark (Sep 1 - Nov 18, 2026 | 54 NSE Sessions | Rs 50,000 Wallet):
  - Net Profit    : Rs +46,014.90 (+92.03%)
  - Trades / WR   : 95 (56W/39L, 59.0%)
  - Profit Factor : 1.595 | Max DD: Rs 18,077.60
  - Active Days   : 52/54 (96.3%), Avg 1.76/day

Usage:
  UPSTOX_ACCESS_TOKEN="<token>" python3 bot_11_bb_keltner_lock_2100.py run --wallet 50000
  python3 bot_11_bb_keltner_lock_2100.py status
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bot_runtime import run_bot_cli

BOT_ID = 'bot_11_bb_keltner_lock_2100'
BOT_NAME = 'Bollinger-Keltner Lock Rs2100'
FAMILY = 'Volatility Squeeze Breakout'
DESCRIPTION = 'Volatility band breakout with daily lock at Rs 2100.'

CONFIG = json.loads('''{
    "initial_wallet": 50000.0,
    "capital_floor": 30000.0,
    "safety_buffer": 2000.0,
    "planned_risk": 2800.0,
    "daily_loss_limit": 4000.0,
    "daily_profit_lock": 2100.0,
    "dynamic_risk_scaling": true,
    "max_lots": 2,
    "loss_streak_single_lot": true,
    "loss_streak_lot_cap": 1,
    "target_delta": 0.6,
    "delta_min": 0.4,
    "delta_max": 0.68,
    "max_trades_day": 4,
    "max_loss_streak": 2,
    "stop_fraction": 0.1,
    "target_fraction": 0.38,
    "breakeven_activation_fraction": 0.065,
    "breakeven_lock_fraction": 0.028,
    "trail_activation_fraction": 0.13,
    "trail_fraction": 0.05,
    "step_trail_levels": [
        [
            0.085,
            0.035
        ],
        [
            0.15,
            0.09
        ],
        [
            0.22,
            0.15
        ],
        [
            0.28,
            0.215
        ]
    ],
    "entry_start_clock": "09:20",
    "entry_end_clock": "14:00",
    "force_exit_clock": "15:15",
    "cooldown_minutes": 5,
    "direction_cooldown_minutes": 15,
    "max_hold_minutes": 55,
    "max_premium_loss_fraction": 0.48,
    "vix_min": 14.0,
    "vix_max": 35.0,
    "early_stall_exit": false,
    "early_stall_max_vix": 14.0,
    "stall_minutes": 11.0,
    "low_vix_regime": {
        "enabled": true,
        "vix_min": 10.0,
        "max_lots": 1,
        "target_delta": 0.65,
        "delta_max": 0.76,
        "entry_end_clock": "13:30",
        "max_trades_day": 1,
        "max_hold_minutes": 35,
        "stop_fraction": 0.075,
        "target_fraction": 0.145,
        "breakeven_activation_fraction": 0.045,
        "breakeven_lock_fraction": 0.025,
        "trail_activation_fraction": 0.065,
        "trail_fraction": 0.028,
        "max_premium_loss_fraction": 0.45,
        "early_stall_exit": true,
        "stall_minutes": 11.0,
        "step_trail_levels": [
            [
                0.085,
                0.035
            ],
            [
                0.15,
                0.09
            ],
            [
                0.22,
                0.15
            ],
            [
                0.28,
                0.215
            ]
        ]
    }
}''')


def evaluate_signal(feat: dict, state: dict, cfg: dict):
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


def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None


if __name__ == "__main__":
    run_bot_cli(BOT_ID, BOT_NAME, DESCRIPTION, CONFIG, evaluate_signal, evaluate_exit)
