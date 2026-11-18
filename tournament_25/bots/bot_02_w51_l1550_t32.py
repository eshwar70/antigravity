#!/usr/bin/env python3
"""Rung 02 — WideRunner Boost L1550 T32% (bot_02_w51_l1550_t32) — Standalone Live Upstox Paper Trading Bot.

Rung #02 in Tournament of 25.
Qualification Benchmark (Sep 1 - Nov 18, 2026 | 54 NSE Sessions | Rs 50,000 Starting Wallet):
  - Net Profit    : Rs +23,532.37 (+47.06%)
  - Step Gap      : Rs +3,107.95 above previous competitor (Requirement: >= +Rs 3,000.00)
  - Trades / WR   : 96 trades (52W / 44L, 54.2%)
  - Profit Factor : 1.324 | Max Drawdown: Rs 20,176.77
  - Active Days   : 53/54 (1.78 trades/day)

Usage:
  UPSTOX_ACCESS_TOKEN="<token>" python3 bot_02_w51_l1550_t32.py run --wallet 50000
  python3 bot_02_w51_l1550_t32.py status
  python3 bot_02_w51_l1550_t32.py replay --days 5
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bot_runtime import run_bot_cli

BOT_ID = "bot_02_w51_l1550_t32"
BOT_NAME = "Rung 02 — WideRunner Boost L1550 T32%"
FAMILY = "Asymmetric WideRunner"
DESCRIPTION = "Asymmetric WideRunner with 2 lots, lock Rs 1550, target 32%, trail 5.0%."

CONFIG = json.loads('''{
    "initial_wallet": 50000.0,
    "capital_floor": 30000.0,
    "safety_buffer": 2000.0,
    "planned_risk": 2800.0,
    "daily_loss_limit": 4000.0,
    "daily_profit_lock": 1550.0,
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
    "target_fraction": 0.32,
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


def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    return None


if __name__ == "__main__":
    run_bot_cli(BOT_ID, BOT_NAME, DESCRIPTION, CONFIG, evaluate_signal, evaluate_exit)
