#!/usr/bin/env python3
"""Rung 05 — Tight-Stop L2300 T32% (bot_05_tight_l2300_t32) — Standalone Live Upstox Paper Trading Bot.

Rung #05 in Tournament of 25.
Qualification Benchmark (Sep 1 - Nov 18, 2026 | 54 NSE Sessions | Rs 50,000 Starting Wallet):
  - Net Profit    : Rs +33,891.51 (+67.78%)
  - Step Gap      : Rs +4,107.94 above previous competitor (Requirement: >= +Rs 3,000.00)
  - Trades / WR   : 98 trades (53W / 45L, 54.1%)
  - Profit Factor : 1.559 | Max Drawdown: Rs 20,203.85
  - Active Days   : 52/54 (1.81 trades/day)

Usage:
  UPSTOX_ACCESS_TOKEN="<token>" python3 bot_05_tight_l2300_t32.py run --wallet 50000
  python3 bot_05_tight_l2300_t32.py status
  python3 bot_05_tight_l2300_t32.py replay --days 5
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bot_runtime import run_bot_cli

BOT_ID = "bot_05_tight_l2300_t32"
BOT_NAME = "Rung 05 — Tight-Stop L2300 T32%"
FAMILY = "Tight-Stop Asymmetric R:R"
DESCRIPTION = "Tight-Stop Asymmetric R:R with 2 lots, lock Rs 2300, target 32%, trail 4.5%."

CONFIG = json.loads('''{
    "initial_wallet": 50000.0,
    "capital_floor": 30000.0,
    "safety_buffer": 2000.0,
    "planned_risk": 2600.0,
    "daily_loss_limit": 4000.0,
    "daily_profit_lock": 2300.0,
    "dynamic_risk_scaling": true,
    "max_lots": 2,
    "loss_streak_single_lot": true,
    "loss_streak_lot_cap": 1,
    "target_delta": 0.6,
    "delta_min": 0.4,
    "delta_max": 0.68,
    "max_trades_day": 4,
    "max_loss_streak": 2,
    "stop_fraction": 0.08,
    "target_fraction": 0.32,
    "breakeven_activation_fraction": 0.055,
    "breakeven_lock_fraction": 0.025,
    "trail_activation_fraction": 0.11,
    "trail_fraction": 0.045,
    "step_trail_levels": [
        [
            0.075,
            0.035
        ],
        [
            0.135,
            0.085
        ],
        [
            0.21,
            0.15
        ],
        [
            0.29,
            0.225
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
    if feat["trend_5m"] == 1 and feat["st5m_dir"] == 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 74.0:
            return 1, "TIGHT_RR_L", None
    if feat["trend_5m"] == -1 and feat["st5m_dir"] == -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 26.0:
            return -1, "TIGHT_RR_S", None
    return 0, "NONE", None


def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None


if __name__ == "__main__":
    run_bot_cli(BOT_ID, BOT_NAME, DESCRIPTION, CONFIG, evaluate_signal, evaluate_exit)
