#!/usr/bin/env python3
"""Convex Gamma-50 Tuned Lock Rs2400 (bot_20_gamma50_tuned_l2400) — Live Upstox Paper Trading Bot.

Family      : Convex Gamma Breakout
Description : ATM 0.50 delta gamma convexity with Rs 2400 daily profit lock.
Qualification Benchmark (Sep 1 - Nov 18, 2026 | 54 NSE Sessions | Rs 50,000 Wallet):
  - Net Profit    : Rs +31,312.06 (+62.62%)
  - Trades / WR   : 84 (53W/31L, 63.1%)
  - Profit Factor : 1.621 | Max DD: Rs 11,855.37
  - Active Days   : 47/54 (87.0%), Avg 1.56/day

Usage:
  UPSTOX_ACCESS_TOKEN="<token>" python3 bot_20_gamma50_tuned_l2400.py run --wallet 50000
  python3 bot_20_gamma50_tuned_l2400.py status
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bot_runtime import run_bot_cli

BOT_ID = 'bot_20_gamma50_tuned_l2400'
BOT_NAME = 'Convex Gamma-50 Tuned Lock Rs2400'
FAMILY = 'Convex Gamma Breakout'
DESCRIPTION = 'ATM 0.50 delta gamma convexity with Rs 2400 daily profit lock.'

CONFIG = json.loads('''{
    "initial_wallet": 50000.0,
    "capital_floor": 30000.0,
    "safety_buffer": 2000.0,
    "planned_risk": 3000.0,
    "daily_loss_limit": 4000.0,
    "daily_profit_lock": 2400.0,
    "dynamic_risk_scaling": true,
    "max_lots": 2,
    "loss_streak_single_lot": true,
    "loss_streak_lot_cap": 1,
    "target_delta": 0.5,
    "delta_min": 0.4,
    "delta_max": 0.62,
    "max_trades_day": 4,
    "max_loss_streak": 2,
    "stop_fraction": 0.11,
    "target_fraction": 0.42,
    "breakeven_activation_fraction": 0.07,
    "breakeven_lock_fraction": 0.03,
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
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and feat["roc3"] > 0.0004 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "GAMMA50_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and feat["roc3"] < -0.0004 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "GAMMA50_S", None
    return 0, "NONE", None


def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None


if __name__ == "__main__":
    run_bot_cli(BOT_ID, BOT_NAME, DESCRIPTION, CONFIG, evaluate_signal, evaluate_exit)
