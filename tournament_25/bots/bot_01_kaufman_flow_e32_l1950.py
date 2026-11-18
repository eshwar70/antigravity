#!/usr/bin/env python3
"""Rung 01 — Kaufman Flow E32 Lock Rs1950 (bot_01_kaufman_flow_e32_l1950) — Standalone Live Upstox Paper Trading Bot.

Rung #01 in Tournament of 25.
Qualification Benchmark (Sep 1 - Nov 18, 2026 | 54 NSE Sessions | Rs 50,000 Starting Wallet):
  - Net Profit    : Rs +20,424.42 (+40.85%)
  - Step Gap      : Rs +3,535.88 above previous competitor (Requirement: >= +Rs 3,000.00)
  - Trades / WR   : 83 trades (51W / 32L, 61.5%)
  - Profit Factor : 1.418 | Max Drawdown: Rs 13,153.05
  - Active Days   : 49/54 (1.54 trades/day)

Usage:
  UPSTOX_ACCESS_TOKEN="<token>" python3 bot_01_kaufman_flow_e32_l1950.py run --wallet 50000
  python3 bot_01_kaufman_flow_e32_l1950.py status
  python3 bot_01_kaufman_flow_e32_l1950.py replay --days 5
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bot_runtime import run_bot_cli

BOT_ID = "bot_01_kaufman_flow_e32_l1950"
BOT_NAME = "Rung 01 — Kaufman Flow E32 Lock Rs1950"
FAMILY = "Efficiency Ratio Filter"
DESCRIPTION = "Dual-timeframe Kaufman efficiency (5m >= 0.32, 1m >= 0.28) with Rs 1950 daily profit lock."

CONFIG = json.loads('''{
    "initial_wallet": 50000.0,
    "capital_floor": 30000.0,
    "safety_buffer": 2000.0,
    "planned_risk": 2800.0,
    "daily_loss_limit": 4000.0,
    "daily_profit_lock": 1950.0,
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
    if feat["eff_5m"] >= 0.32 and feat["eff10_1m"] >= 0.28 and feat["esep_5m"] >= 0.35:
        if feat["trend_5m"] == 1 and p > feat["e9"] > feat["e21"] and feat["roc3"] > 0.0004 and br != -1 and feat["rsi14"] <= 76.0:
            return 1, "KAUFMAN_L", None
        if feat["trend_5m"] == -1 and p < feat["e9"] < feat["e21"] and feat["roc3"] < -0.0004 and br != 1 and feat["rsi14"] >= 24.0:
            return -1, "KAUFMAN_S", None
    return 0, "NONE", None


def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None


if __name__ == "__main__":
    run_bot_cli(BOT_ID, BOT_NAME, DESCRIPTION, CONFIG, evaluate_signal, evaluate_exit)
