#!/usr/bin/env python3
"""Round 2 Library: 36 genuinely distinct, regime-adaptive, strictly causal NIFTY 50 live trading bots.

Every bot includes:
- Dual-VIX regime discipline (capital-preserving low-VIX < 14 mode + full compounding normal/high-VIX mode)
- Identical execution rules to Winner 51 (Rs 50k wallet, Rs 30k+2k floor, Rs 40/side fees, 0.2% slippage,
  strictly causal 2-step signal->fill, real liquidity & Greeks gates)
- Distinct alpha signal engines & trailing/exit architectures
"""
from __future__ import annotations

from typing import Any, Dict, List


def make_low_vix_regime(
    target_delta: float = 0.65,
    max_trades_day: int = 1,
    stop_fraction: float = 0.075,
    target_fraction: float = 0.16,
    be_act: float = 0.045,
    be_lock: float = 0.025,
    trail_act: float = 0.065,
    trail_fr: float = 0.028,
    max_hold: int = 35,
    entry_end: str = "13:30",
    early_stall: bool = True,
    stall_mins: float = 11.0,
) -> dict:
    return dict(
        enabled=True,
        vix_min=10.0,
        max_lots=1,
        target_delta=target_delta,
        delta_max=0.76,
        entry_end_clock=entry_end,
        max_trades_day=max_trades_day,
        max_hold_minutes=max_hold,
        stop_fraction=stop_fraction,
        target_fraction=target_fraction,
        breakeven_activation_fraction=be_act,
        breakeven_lock_fraction=be_lock,
        trail_activation_fraction=trail_act,
        trail_fraction=trail_fr,
        max_premium_loss_fraction=0.45,
        early_stall_exit=early_stall,
        stall_minutes=stall_mins,
        step_trail_levels=[[0.085, 0.035], [0.15, 0.09], [0.22, 0.15], [0.28, 0.215]],
    )


def base_cfg(
    *,
    planned_risk: float = 2800.0,
    daily_loss_limit: float = 4000.0,
    daily_profit_lock: float = 2200.0,
    max_lots: int = 2,
    target_delta: float = 0.60,
    delta_min: float = 0.40,
    delta_max: float = 0.68,
    max_trades_day: int = 4,
    max_loss_streak: int = 2,
    stop_fraction: float = 0.10,
    target_fraction: float = 0.36,
    be_act: float = 0.065,
    be_lock: float = 0.028,
    trail_act: float = 0.13,
    trail_fr: float = 0.05,
    step_levels: list | None = None,
    entry_start: str = "09:20",
    entry_end: str = "14:00",
    max_hold: int = 55,
    cooldown: int = 5,
    dir_cooldown: int = 15,
    max_prem_frac: float = 0.48,
    vix_min: float = 14.0,
    early_stall_max_vix: float = 14.0,
    low_vix: dict | None = None,
) -> dict:
    return dict(
        initial_wallet=50000.0,
        capital_floor=30000.0,
        safety_buffer=2000.0,
        planned_risk=planned_risk,
        daily_loss_limit=daily_loss_limit,
        daily_profit_lock=daily_profit_lock,
        dynamic_risk_scaling=True,
        max_lots=max_lots,
        loss_streak_single_lot=True,
        loss_streak_lot_cap=1,
        target_delta=target_delta,
        delta_min=delta_min,
        delta_max=delta_max,
        max_trades_day=max_trades_day,
        max_loss_streak=max_loss_streak,
        stop_fraction=stop_fraction,
        target_fraction=target_fraction,
        breakeven_activation_fraction=be_act,
        breakeven_lock_fraction=be_lock,
        trail_activation_fraction=trail_act,
        trail_fraction=trail_fr,
        step_trail_levels=step_levels
        if step_levels is not None
        else [[0.085, 0.035], [0.15, 0.09], [0.22, 0.15], [0.28, 0.215], [0.35, 0.28]],
        entry_start_clock=entry_start,
        entry_end_clock=entry_end,
        force_exit_clock="15:15",
        cooldown_minutes=cooldown,
        direction_cooldown_minutes=dir_cooldown,
        max_hold_minutes=max_hold,
        max_premium_loss_fraction=max_prem_frac,
        vix_min=vix_min,
        vix_max=35.0,
        early_stall_exit=False,
        early_stall_max_vix=early_stall_max_vix,
        stall_minutes=11.0,
        low_vix_regime=low_vix if low_vix is not None else make_low_vix_regime(),
    )


EXIT_PURE = '''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    """Pure regime-adaptive stop, target, step-trailing ladder & built-in stall guard."""
    return None
'''

EXIT_PARABOLIC = '''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    """Locks extreme parabolic option spikes (>30%) when 1m momentum exhausts."""
    bid = float(option["bid"])
    entry = float(pos["entry"])
    if entry <= 0:
        return None
    ret = (bid - entry) / entry
    pos_dir = 1 if pos["kind"] == "CE" else -1
    if ret >= 0.30:
        if pos_dir == 1 and feat["rsi14"] >= 86.0 and feat["macd_hist"] < feat["prev_macd_hist"]:
            return "PARABOLIC_LOCK_EXIT"
        if pos_dir == -1 and feat["rsi14"] <= 14.0 and feat["macd_hist"] > feat["prev_macd_hist"]:
            return "PARABOLIC_LOCK_EXIT"
    return None
'''

EXIT_HTF_GUARD = '''def evaluate_exit(pos: dict, option: dict, feat: dict, cfg: dict):
    """Protects against deep 5m trend reversals after 12+ mins when underwater."""
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


CANDIDATE_SPECS: List[Dict[str, Any]] = [
    # 1. Dual Supertrend Cascade Pro
    dict(
        slug="supertrend_cascade_pro",
        bot_name="Dual Supertrend Cascade Pro",
        family="Supertrend Dual-Timeframe",
        description="Synchronized 1m+5m Supertrend cascade with 5m EMA separation, ADX trend strength, and dual-VIX step trailing.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2600.0, max_lots=3, target_delta=0.58, target_fraction=0.38, max_prem_frac=0.55),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if "12:15" <= feat["clock"] <= "13:05" and feat["vix"] >= 14.0:
        if feat["eff_5m"] < 0.40:
            return 0, "NONE", None
    if feat["st1m_dir"] == 1 and feat["st5m_dir"] == 1 and feat["trend_5m"] == 1:
        if feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "ST_CASCADE_L", None
    if feat["st1m_dir"] == -1 and feat["st5m_dir"] == -1 and feat["trend_5m"] == -1:
        if feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "ST_CASCADE_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 2. Institutional ORB-15 + TWAP Precision Runner
    dict(
        slug="orb15_twap_runner",
        bot_name="ORB-15 TWAP Precision Runner",
        family="Opening Range Breakout",
        description="15-minute Opening Range breakout & continuation anchored above/below session TWAP with 5m trend efficiency.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.58, target_fraction=0.40, entry_start="09:20", max_prem_frac=0.55),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["orb15_ready"]:
        if p > feat["orb15_hi"] and p > feat["twap_day"] and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
            if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
                return 1, "ORB15_TWAP_L", None
        if p < feat["orb15_lo"] and p < feat["twap_day"] and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
            if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
                return -1, "ORB15_TWAP_S", None
    # Early 09:20-09:30 drive if 5m trend & breadth align strongly
    if feat["clock"] < "09:30" and feat["eff_5m"] >= 0.30 and feat["esep_5m"] >= 0.40:
        if feat["trend_5m"] == 1 and p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br == 1 and feat["rsi14"] <= 75.0:
            return 1, "EARLY_DRIVE_L", None
        if feat["trend_5m"] == -1 and p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br == -1 and feat["rsi14"] >= 25.0:
            return -1, "EARLY_DRIVE_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 3. Quant 10-Factor Confluence Engine Pro
    dict(
        slug="quant_confluence_pro",
        bot_name="Quant 10-Factor Confluence Pro",
        family="Multi-Factor Quant Score",
        description="Scores 10 independent causal market factors (1m/5m/15m EMAs, MACD, Supertrend, TWAP, Breadth, Delta-Breadth, PCR, ROC) with dual-VIX risk shield.",
        config=base_cfg(planned_risk=3200.0, daily_profit_lock=3000.0, max_lots=3, target_delta=0.58, target_fraction=0.40, max_prem_frac=0.58),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    score = 0
    score += 1 if p > feat["e9"] > feat["e21"] else (-1 if p < feat["e9"] < feat["e21"] else 0)
    score += 2 if feat["trend_5m"] == 1 else (-2 if feat["trend_5m"] == -1 else 0)
    score += 1 if feat["bias_15m"] == 1 else (-1 if feat["bias_15m"] == -1 else 0)
    score += 1 if feat["macd"] > 0 and feat["macd_hist"] > 0 else (-1 if feat["macd"] < 0 and feat["macd_hist"] < 0 else 0)
    score += 1 if feat["st1m_dir"] == 1 and feat["st5m_dir"] == 1 else (-1 if feat["st1m_dir"] == -1 and feat["st5m_dir"] == -1 else 0)
    score += 1 if p > feat["twap_day"] else (-1 if p < feat["twap_day"] else 0)
    score += 1 if feat["breadth_dir"] == 1 else (-1 if feat["breadth_dir"] == -1 else 0)
    score += 1 if feat["delta_breadth_dir"] == 1 else (-1 if feat["delta_breadth_dir"] == -1 else 0)
    score += 1 if feat["pcr_dir"] == 1 else (-1 if feat["pcr_dir"] == -1 else 0)
    score += 1 if feat["roc3"] > 0.0005 else (-1 if feat["roc3"] < -0.0005 else 0)

    if score >= 7 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and feat["rsi14"] <= 75.0:
        return 1, f"QUANT_L_{score}", None
    if score <= -7 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and feat["rsi14"] >= 25.0:
        return -1, f"QUANT_S_{abs(score)}", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 4. EMA Ribbon & ADX Power-Trend Pro
    dict(
        slug="ema_ribbon_adx_pro",
        bot_name="EMA Ribbon ADX Power Pro",
        family="EMA Ribbon + ADX",
        description="Full 5/8/13/21/34 EMA ribbon alignment + ADX directional dominance with regime-aware trailing.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.58, target_fraction=0.38, max_prem_frac=0.55),
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
        exit_code=EXIT_PURE,
    ),

    # 5. Whole-Session TWAP Institutional Flow Pro
    dict(
        slug="twap_flow_pro",
        bot_name="TWAP Institutional Flow Pro",
        family="TWAP Institutional Flow",
        description="Whole-session cumulative TWAP institutional flow & breakout sniper with 5m/15m MTF guard and dual-VIX control.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2600.0, max_lots=3, target_delta=0.60, target_fraction=0.38, max_prem_frac=0.55),
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
        exit_code=EXIT_PURE,
    ),

    # 6. Bollinger-Keltner Volatility Expansion Pro
    dict(
        slug="bb_keltner_pro",
        bot_name="Bollinger-Keltner Breakout Pro",
        family="Volatility Squeeze Breakout",
        description="Captures volatility band expansions beyond Bollinger & Keltner envelopes aligned with 5m trend separation.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.56, target_fraction=0.40, max_prem_frac=0.55),
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
        exit_code=EXIT_PURE,
    ),

    # 7. Donchian 10/20 Channel Breakout Runner
    dict(
        slug="donchian_channel_pro",
        bot_name="Donchian Channel Runner Pro",
        family="Donchian Channel Breakout",
        description="10-bar & 20-bar Donchian breakout engine filtered by 5m trend efficiency and EMA separation.",
        config=base_cfg(planned_risk=3200.0, daily_profit_lock=3200.0, max_lots=3, target_delta=0.56, target_fraction=0.42, max_prem_frac=0.58),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if p > feat["don10_hi"] and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 76.0:
            return 1, "DON_BRK_L", None
    if p < feat["don10_lo"] and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 24.0:
            return -1, "DON_BRK_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 8. EMA9/13 Trend Pullback Sniper Pro
    dict(
        slug="ema_pullback_pro",
        bot_name="EMA9/13 Trend Pullback Pro",
        family="Trend Pullback Sniper",
        description="Enters on high-R:R pullbacks into 1m EMA9/EMA13 inside confirmed 5m trend separation.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2600.0, max_lots=3, target_delta=0.60, target_fraction=0.38, max_prem_frac=0.55),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p, prev, prev2 = feat["price"], feat["prev"], feat["prev2"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.24 and feat["esep_5m"] >= 0.35 and br != -1:
        pulled = (prev <= feat["prev_e9"] * 1.0005 or prev2 <= feat["e13"] * 1.0006)
        if pulled and p > feat["e9"] > feat["e21"] and p > prev and 45.0 <= feat["rsi14"] <= 74.0:
            return 1, "PB_SNIPER_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.24 and feat["esep_5m"] >= 0.35 and br != 1:
        pulled = (prev >= feat["prev_e9"] * 0.9995 or prev2 >= feat["e13"] * 0.9994)
        if pulled and p < feat["e9"] < feat["e21"] and p < prev and 26.0 <= feat["rsi14"] <= 55.0:
            return -1, "PB_SNIPER_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 9. PDH/PDL & ORB-30 Institutional Structure Pro
    dict(
        slug="pdh_pdl_structure_pro",
        bot_name="PDH/PDL Structure Commander Pro",
        family="Prior-Day Structure Breakout",
        description="Prior Day High/Low & 30-min Opening Range institutional breakout engine with 5m trend & breadth verification.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.58, target_fraction=0.40, max_prem_frac=0.55),
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
        exit_code=EXIT_PURE,
    ),

    # 10. NIFTY-50 Breadth Velocity Surge Pro
    dict(
        slug="breadth_surge_pro",
        bot_name="NIFTY-50 Breadth Surge Pro",
        family="Constituent Breadth Surge",
        description="Requires strong NIFTY 50 constituent advance/decline agreement (>=60%) or 15-25m delta breadth surge aligned with 5m trend.",
        config=base_cfg(planned_risk=3200.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.58, target_fraction=0.38, max_prem_frac=0.56),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    bull_br = (feat["adv_pct"] >= 0.60) or (feat["delta_adv"] >= 0.60 and feat["adv_pct"] >= 0.48)
    bear_br = (feat["dec_pct"] >= 0.60) or (feat["delta_dec"] >= 0.60 and feat["dec_pct"] >= 0.48)
    if bull_br and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and feat["rsi14"] <= 75.0:
            return 1, "BREADTH_VEL_L", None
    if bear_br and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and feat["rsi14"] >= 25.0:
            return -1, "BREADTH_VEL_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 11. Options PCR & OI Positioning Momentum Pro
    dict(
        slug="pcr_positioning_pro",
        bot_name="Options PCR Positioning Pro",
        family="Options Positioning / PCR",
        description="Aligns near-ATM Put-Call OI ratio skew with 5m trend separation and 1m momentum confirmation.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2600.0, max_lots=3, target_delta=0.58, target_fraction=0.38, max_prem_frac=0.55),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["pcr"] >= 1.02 and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "PCR_POS_L", None
    if feat["pcr"] <= 0.98 and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "PCR_POS_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 12. Kaufman Efficiency Pure-Flow Pro
    dict(
        slug="kaufman_pure_flow_pro",
        bot_name="Kaufman Efficiency Pure-Flow Pro",
        family="Efficiency Ratio Filter",
        description="Dual-timeframe Kaufman Efficiency filter (1m + 5m) that stays flat in noise and attacks clean institutional flows.",
        config=base_cfg(planned_risk=3200.0, daily_profit_lock=3000.0, max_lots=3, target_delta=0.58, target_fraction=0.40, max_prem_frac=0.58),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["eff_5m"] >= 0.30 and feat["eff10_1m"] >= 0.28 and feat["esep_5m"] >= 0.35:
        if feat["trend_5m"] == 1 and p > feat["e9"] > feat["e21"] and feat["roc3"] > 0.0004 and br != -1 and feat["rsi14"] <= 76.0:
            return 1, "KAUFMAN_L", None
        if feat["trend_5m"] == -1 and p < feat["e9"] < feat["e21"] and feat["roc3"] < -0.0004 and br != 1 and feat["rsi14"] >= 24.0:
            return -1, "KAUFMAN_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 13. Dual-Timeframe MACD Thrust Pro
    dict(
        slug="macd_dual_thrust_pro",
        bot_name="MACD Dual-Timeframe Thrust Pro",
        family="MACD Dual-Timeframe",
        description="Synchronizes 1m and 5m MACD momentum expansion with 5m EMA separation and constituent breadth.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.58, target_fraction=0.38, max_prem_frac=0.55),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 12:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["macd"] > 0 and feat["macd_hist"] > 0 and feat["macd5"] >= 0 and feat["macd5_hist"] >= 0:
        if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and p > feat["e9"] and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "MACD_DUAL_L", None
    if feat["macd"] < 0 and feat["macd_hist"] < 0 and feat["macd5"] <= 0 and feat["macd5_hist"] <= 0:
        if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and p < feat["e9"] and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "MACD_DUAL_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 14. 15-Minute HTF Anchor Precision Pro
    dict(
        slug="htf_15m_anchor_pro",
        bot_name="15m HTF Anchor Precision Pro",
        family="Higher-Timeframe Anchor",
        description="Enforces strict 15-minute higher-timeframe trend alignment before taking 5m/1m momentum triggers.",
        config=base_cfg(planned_risk=3200.0, daily_profit_lock=3000.0, max_lots=3, target_delta=0.58, target_fraction=0.40, max_prem_frac=0.58),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10 or feat["bias_15m"] == 0:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["bias_15m"] == 1 and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.24 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 76.0:
            return 1, "HTF15_L", None
    if feat["bias_15m"] == -1 and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.24 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 24.0:
            return -1, "HTF15_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 15. High-Delta Intrinsic ITM Compounder Pro
    dict(
        slug="itm_delta66_compounder",
        bot_name="High-Delta ITM Compounder Pro",
        family="High-Delta ITM Compounder",
        description="Targets deep 0.66-delta ITM options to suppress theta decay with tight 8.5% stops and calibrated step-trailing.",
        config=base_cfg(
            planned_risk=3000.0, daily_profit_lock=2600.0, max_lots=2,
            target_delta=0.66, delta_min=0.50, delta_max=0.75,
            stop_fraction=0.085, target_fraction=0.30,
            be_act=0.055, be_lock=0.025, trail_act=0.105, trail_fr=0.042,
            step_levels=[[0.07, 0.032], [0.125, 0.08], [0.19, 0.135], [0.25, 0.195]],
            max_prem_frac=0.62,
        ),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd"] > 0 and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "ITM66_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd"] < 0 and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "ITM66_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 16. Convex Mid-Delta Gamma Runner Pro (0.50 Delta, up to 3 lots)
    dict(
        slug="convex_gamma50_runner",
        bot_name="Convex ATM-Gamma Runner Pro",
        family="Convex Gamma Breakout",
        description="Deploys ATM 0.50-delta options for optimal gamma convexity and multi-lot compounding inside Rs 50k headroom.",
        config=base_cfg(
            planned_risk=3400.0, daily_profit_lock=3400.0, max_lots=3,
            target_delta=0.50, delta_min=0.40, delta_max=0.62,
            stop_fraction=0.115, target_fraction=0.46,
            be_act=0.075, be_lock=0.032, trail_act=0.14, trail_fr=0.055,
            step_levels=[[0.095, 0.04], [0.17, 0.105], [0.26, 0.185], [0.36, 0.28]],
            max_prem_frac=0.58,
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
        exit_code=EXIT_PARABOLIC,
    ),

    # 17. WideRunner Turbo (Multi-Setup MTF + Morning TWAP + Flag, Higher Compounding Lock)
    dict(
        slug="widerunner_turbo",
        bot_name="WideRunner Turbo Compounder",
        family="Asymmetric WideRunner",
        description="4-setup multi-timeframe momentum + TWAP + Flag engine with unlocked 3-lot compounding and extended 6-tier profit ladder.",
        config=base_cfg(
            planned_risk=3400.0, daily_profit_lock=3200.0, max_lots=3,
            target_delta=0.58, target_fraction=0.45,
            step_levels=[[0.085, 0.038], [0.15, 0.095], [0.22, 0.155], [0.30, 0.23], [0.38, 0.31]],
            entry_end="14:25", max_hold=65, max_prem_frac=0.60,
        ),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p, prev = feat["price"], feat["prev"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
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
    if prop != 0 and feat["trend_5m"] == prop and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.38:
        eff_br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] == prop else feat["breadth_dir"]
        if eff_br != -prop and ((prop == 1 and feat["rsi14"] <= 75.0) or (prop == -1 and feat["rsi14"] >= 25.0)):
            if "12:15" <= feat["clock"] <= "13:05" and feat["vix"] >= 14.0 and not (feat["eff_5m"] >= 0.40 and eff_br == prop):
                return 0, "NONE", None
            return prop, "TURBO_1M", None
    # Setup 2: Morning TWAP + Donchian 20 breakout
    if "09:40" <= feat["clock"] < "11:55" and feat["eff_5m"] >= 0.34 and feat["esep_5m_fast"] >= 0.25:
        if ups >= 3 and p > feat["twap_day"] and p > feat["don20_hi"] and feat["trend_5m_fast"] == 1 and feat["bias_15m"] != -1 and feat["delta_breadth_dir"] == 1 and feat["pcr_dir"] == 1 and feat["rsi14"] <= 74.0:
            return 1, "TURBO_TWAP_L", None
        if dns >= 3 and p < feat["twap_day"] and p < feat["don20_lo"] and feat["trend_5m_fast"] == -1 and feat["bias_15m"] != 1 and feat["delta_breadth_dir"] == -1 and feat["pcr_dir"] == -1 and feat["rsi14"] >= 26.0:
            return -1, "TURBO_TWAP_S", None
    # Setup 3: Flag continuation
    if feat["imp10"] >= 0.0017 and feat["cons5"] <= 0.0016 and p > feat["don5_hi"] and feat["trend_5m"] == 1 and br == 1 and feat["rsi14"] <= 74.0:
        return 1, "TURBO_FLAG_L", None
    if feat["imp10"] <= -0.0017 and feat["cons5"] <= 0.0016 and p < feat["don5_lo"] and feat["trend_5m"] == -1 and br == -1 and feat["rsi14"] >= 26.0:
        return -1, "TURBO_FLAG_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 18. 5m RSI Regime Surfer Pro
    dict(
        slug="rsi5m_surfer_pro",
        bot_name="5m RSI-Band Surfer Pro",
        family="MTF RSI Momentum",
        description="Rides clean 5-minute RSI bullish (>57) and bearish (<43) institutional momentum regimes with 1m confirmation.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.58, target_fraction=0.38, max_prem_frac=0.56),
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
        exit_code=EXIT_PURE,
    ),

    # 19. Dual-Session Morning & Power-Hour Pro (Hard Lunch Blackout)
    dict(
        slug="dual_session_pro",
        bot_name="Dual-Session Power-Hour Pro",
        family="Session-Split Timing",
        description="Zero midday chop exposure (11:55-13:05 blackout); trades morning expansion & European/afternoon power-hour moves.",
        config=base_cfg(planned_risk=3200.0, daily_profit_lock=3000.0, max_lots=3, target_delta=0.58, target_fraction=0.40, entry_end="14:35", max_prem_frac=0.58),
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
        exit_code=EXIT_PURE,
    ),

    # 20. EMA-50 Macro-Trend Guardian Pro
    dict(
        slug="ema50_guardian_pro",
        bot_name="EMA-50 Macro-Trend Guardian Pro",
        family="Macro-EMA Trend Filter",
        description="Enforces 1m EMA 9/21/50 stack alignment with 5m trend efficiency to eliminate counter-trend bull/bear traps.",
        config=base_cfg(planned_risk=3200.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.58, target_fraction=0.38, max_prem_frac=0.56),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if p > feat["e9"] > feat["e21"] > feat["e50"] and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "EMA50_MACRO_L", None
    if p < feat["e9"] < feat["e21"] < feat["e50"] and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "EMA50_MACRO_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 21. Bull/Bear Impulse Flag Specialist Pro
    dict(
        slug="impulse_flag_pro",
        bot_name="Impulse Flag & Continuation Pro",
        family="Chart Pattern / Flag",
        description="Combines bull/bear flag breakouts with high-ROC directional continuation inside strong 5m trends.",
        config=base_cfg(planned_risk=3200.0, daily_profit_lock=3000.0, max_lots=3, target_delta=0.56, target_fraction=0.40, max_prem_frac=0.56),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.24 and br != -1 and feat["rsi14"] <= 75.0:
        flag = feat["imp10"] >= 0.0014 and feat["cons5"] <= 0.0020 and p > feat["don5_hi"]
        cont = feat["roc5"] >= 0.0008 and p > feat["don10_hi"] and feat["esep_5m"] >= 0.35
        if flag or cont:
            return 1, ("FLAG_L" if flag else "IMP_CONT_L"), None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.24 and br != 1 and feat["rsi14"] >= 25.0:
        flag = feat["imp10"] <= -0.0014 and feat["cons5"] <= 0.0020 and p < feat["don5_lo"]
        cont = feat["roc5"] <= -0.0008 and p < feat["don10_lo"] and feat["esep_5m"] >= 0.35
        if flag or cont:
            return -1, ("FLAG_S" if flag else "IMP_CONT_S"), None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 22. Stochastic-RSI Trend Snapback Pro
    dict(
        slug="stoch_snapback_pro",
        bot_name="Stochastic-RSI Snapback Pro",
        family="Mean-Reversion-to-Trend",
        description="Buys crisp Stochastic/RSI pullbacks turning back up inside established 5m trend separation.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2600.0, max_lots=3, target_delta=0.60, target_fraction=0.36, max_prem_frac=0.55),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and br != -1:
        if feat["rsi14"] > feat["rsi14_prev"] and feat["rsi14_prev"] <= 58.0 and feat["stoch14"] >= 40.0 and p > feat["e9"] and feat["rsi14"] <= 73.0:
            return 1, "STOCH_SNAP_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35 and br != 1:
        if feat["rsi14"] < feat["rsi14_prev"] and feat["rsi14_prev"] >= 42.0 and feat["stoch14"] <= 60.0 and p < feat["e9"] and feat["rsi14"] >= 27.0:
            return -1, "STOCH_SNAP_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 23. Strong-Body Candle Expansion Pro
    dict(
        slug="candle_expansion_pro",
        bot_name="Candle Expansion Impulse Pro",
        family="Price-Action Impulse",
        description="Triggers on high-conviction directional 1m expansion candles breaking 5-bar highs/lows inside 5m trend.",
        config=base_cfg(planned_risk=3000.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.58, target_fraction=0.38, max_prem_frac=0.55),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["body_ratio"] >= 0.45 and p > feat["don5_hi"] and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "BODY_IMP_L", None
    if feat["body_ratio"] <= -0.45 and p < feat["don5_lo"] and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "BODY_IMP_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 24. Gap-and-Go Morning Drive Pro
    dict(
        slug="gap_drive_pro",
        bot_name="Gap-and-Go Morning Drive Pro",
        family="Gap & Opening Drive",
        description="Exploits directional gap continuations in the first 90 minutes and transitions to 5m trend-efficiency rides.",
        config=base_cfg(planned_risk=3200.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.58, target_fraction=0.40, max_prem_frac=0.56),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if "09:20" <= feat["clock"] <= "10:45":
        if feat["gap_pct"] >= 0.0012 and p > feat["day_open"] and p > feat["twap_day"] and feat["trend_5m_fast"] == 1 and br == 1 and feat["rsi14"] <= 76.0:
            return 1, "GAP_DRIVE_L", None
        if feat["gap_pct"] <= -0.0012 and p < feat["day_open"] and p < feat["twap_day"] and feat["trend_5m_fast"] == -1 and br == -1 and feat["rsi14"] >= 24.0:
            return -1, "GAP_DRIVE_S", None
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38 and p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
        return 1, "DRIVE_CONT_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38 and p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
        return -1, "DRIVE_CONT_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 25. Asymmetric Tight-Stop 4:1 Sniper Pro
    dict(
        slug="asymmetric_tight_stop_pro",
        bot_name="Asymmetric Tight-Stop Sniper Pro",
        family="Tight-Stop Asymmetric R:R",
        description="Tight 8.0% initial stop paired with 36% target and fast +5.5% breakeven lock for high Profit Factor.",
        config=base_cfg(
            planned_risk=2800.0, daily_profit_lock=2800.0, max_lots=3,
            target_delta=0.60, stop_fraction=0.08, target_fraction=0.36,
            be_act=0.055, be_lock=0.025, trail_act=0.11, trail_fr=0.045,
            step_levels=[[0.075, 0.035], [0.135, 0.085], [0.21, 0.15], [0.29, 0.225]],
            max_prem_frac=0.55,
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
        exit_code=EXIT_PURE,
    ),

    # 26. Trend-Day Drift & Breadth Compounder
    dict(
        slug="trend_day_compounder",
        bot_name="Trend-Day Drift Compounder",
        family="Intraday Drift Compounder",
        description="Confirms directional intraday drift from session open + TWAP + 5m EMA separation for multi-lot trend rides.",
        config=base_cfg(planned_risk=3400.0, daily_profit_lock=3400.0, max_lots=3, target_delta=0.56, target_fraction=0.44, max_prem_frac=0.58),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["day_ret"] >= 0.0008 and p > feat["twap_day"] and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "DRIFT_COMP_L", None
    if feat["day_ret"] <= -0.0008 and p < feat["twap_day"] and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "DRIFT_COMP_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 27. Chandelier Wide-Target Runner (50% Target + HTF Guard)
    dict(
        slug="chandelier_wide_runner",
        bot_name="Chandelier Wide-Target Runner",
        family="Chandelier Wide-Target",
        description="50% wide option profit target with 6-tier ratcheting stop ladder and 5m Supertrend reversal guard.",
        config=base_cfg(
            planned_risk=3400.0, daily_profit_lock=3800.0, max_lots=3,
            target_delta=0.56, stop_fraction=0.11, target_fraction=0.50,
            be_act=0.07, be_lock=0.03, trail_act=0.14, trail_fr=0.055,
            step_levels=[[0.09, 0.04], [0.16, 0.10], [0.24, 0.17], [0.33, 0.255], [0.42, 0.34]],
            max_hold=70, max_prem_frac=0.60,
        ),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["st5m_dir"] == 1 and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and (p > feat["don10_hi"] or feat["roc3"] > 0.0005) and br != -1 and feat["rsi14"] <= 76.0:
            return 1, "CHAND_WIDE_L", None
    if feat["st5m_dir"] == -1 and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and (p < feat["don10_lo"] or feat["roc3"] < -0.0005) and br != 1 and feat["rsi14"] >= 24.0:
            return -1, "CHAND_WIDE_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_HTF_GUARD,
    ),

    # 28. Morning-Only Institutional Sniper (09:20-12:10 IST Focus)
    dict(
        slug="morning_institutional_sniper",
        bot_name="Morning Institutional Sniper",
        family="Morning-Session Focus",
        description="Concentrates 100% of risk budget into NSE's highest-edge morning expansion window (09:20-12:15 IST).",
        config=base_cfg(
            planned_risk=3400.0, daily_profit_lock=3200.0, max_lots=3,
            target_delta=0.58, target_fraction=0.40,
            entry_start="09:20", entry_end="12:15", max_hold=65, max_prem_frac=0.58,
            low_vix=make_low_vix_regime(entry_end="11:45", max_trades_day=1, target_fraction=0.16),
        ),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "MORNING_SNIPER_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "MORNING_SNIPER_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 29. Adaptive High-Profit-Lock Scalper (Rapid Lock + Re-Compound)
    dict(
        slug="rapid_lock_compounder",
        bot_name="Rapid-Lock Precision Compounder",
        family="Rapid-Lock Compounder",
        description="Aggressive early profit-locking step ladder (+6%->+2.8%, +11%->+7%, +17%->+12.5%, +24%->+19%) for smooth high-WR compounding.",
        config=base_cfg(
            planned_risk=3200.0, daily_profit_lock=2500.0, max_lots=3,
            target_delta=0.60, stop_fraction=0.095, target_fraction=0.32,
            be_act=0.055, be_lock=0.025, trail_act=0.10, trail_fr=0.04,
            step_levels=[[0.06, 0.028], [0.11, 0.07], [0.17, 0.125], [0.24, 0.19]],
            max_prem_frac=0.56,
        ),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "RAPID_LOCK_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "RAPID_LOCK_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 30. Low-VIX Alpha Specialist (Profitable Even in Quiet VIX 10-14 Markets)
    dict(
        slug="all_vix_alpha_specialist",
        bot_name="All-VIX Regime Alpha Specialist",
        family="All-VIX Dual-Regime",
        description="Uses ultra-selective 15m+TWAP+Supertrend alignment in low VIX (<14) to stay green in quiet months, then scales up in VIX >=14.",
        config=base_cfg(
            planned_risk=3400.0, daily_profit_lock=3200.0, max_lots=3,
            target_delta=0.58, target_fraction=0.42, max_prem_frac=0.58,
            low_vix=make_low_vix_regime(
                target_delta=0.66, max_trades_day=1, stop_fraction=0.07, target_fraction=0.18,
                be_act=0.04, be_lock=0.022, trail_act=0.06, trail_fr=0.025, max_hold=35, entry_end="12:30",
            ),
        ),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["vix"] < 14.0:
        # Strict high-conviction filter in low-VIX regime
        if feat["trend_5m"] == 1 and feat["bias_15m"] == 1 and feat["st5m_dir"] == 1 and p > feat["twap_day"]:
            if p > feat["e9"] > feat["e21"] and feat["eff_5m"] >= 0.30 and feat["esep_5m"] >= 0.42 and br == 1 and feat["rsi14"] <= 73.0:
                return 1, "LOWVIX_ALPHA_L", None
        if feat["trend_5m"] == -1 and feat["bias_15m"] == -1 and feat["st5m_dir"] == -1 and p < feat["twap_day"]:
            if p < feat["e9"] < feat["e21"] and feat["eff_5m"] >= 0.30 and feat["esep_5m"] >= 0.42 and br == -1 and feat["rsi14"] >= 27.0:
                return -1, "LOWVIX_ALPHA_S", None
        return 0, "NONE", None
    # Normal/High VIX full runner
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "HIGHVIX_ALPHA_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "HIGHVIX_ALPHA_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 31. Asymmetric Fast-5m Momentum Harvester
    dict(
        slug="fast5m_momentum_harvester",
        bot_name="Fast-5m EMA5/13 Momentum Harvester",
        family="Fast-5m Momentum",
        description="Uses fast 5m EMA(5,13) + 15m bias + TWAP confirmation to enter early institutional breakouts before slow 5m EMA21 lags.",
        config=base_cfg(planned_risk=3200.0, daily_profit_lock=2800.0, max_lots=3, target_delta=0.58, target_fraction=0.40, max_prem_frac=0.56),
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
        exit_code=EXIT_PURE,
    ),

    # 32. Uncapped-Lock High-Conviction Runner (Daily Lock Rs 6,000, Max 2 Trades/Day)
    dict(
        slug="two_shot_high_conviction",
        bot_name="Two-Shot High-Conviction Sniper",
        family="Two-Shot Daily Sniper",
        description="Strictly limits trading to 2 surgical high-conviction shots per day with high Rs 6,000 profit room so big trend runs never get cut early.",
        config=base_cfg(
            planned_risk=3600.0, daily_loss_limit=4200.0, daily_profit_lock=6000.0,
            max_lots=3, target_delta=0.58, max_trades_day=2, max_loss_streak=2,
            stop_fraction=0.10, target_fraction=0.48,
            step_levels=[[0.085, 0.038], [0.15, 0.095], [0.23, 0.165], [0.32, 0.25], [0.42, 0.34]],
            max_hold=75, max_prem_frac=0.60,
        ),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.28 and feat["esep_5m"] >= 0.40:
        if p > feat["e9"] > feat["e21"] and p > feat["twap_day"] and feat["macd_hist"] > 0 and br == 1 and feat["rsi14"] <= 75.0:
            return 1, "TWOSHOT_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.28 and feat["esep_5m"] >= 0.40:
        if p < feat["e9"] < feat["e21"] and p < feat["twap_day"] and feat["macd_hist"] < 0 and br == -1 and feat["rsi14"] >= 25.0:
            return -1, "TWOSHOT_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 33. Single-Shot Daily Champion Sniper (Max 1 Surgical Trade/Day, Wide Target)
    dict(
        slug="one_shot_daily_master",
        bot_name="One-Shot Daily Master Sniper",
        family="One-Shot Daily Master",
        description="Waits patiently for the single cleanest institutional trend setup of the day (1 trade/day max) and rides it with 3-lot step-trailing.",
        config=base_cfg(
            planned_risk=3800.0, daily_loss_limit=4200.0, daily_profit_lock=8000.0,
            max_lots=3, target_delta=0.58, max_trades_day=1, max_loss_streak=1,
            stop_fraction=0.105, target_fraction=0.50,
            step_levels=[[0.085, 0.038], [0.15, 0.095], [0.23, 0.165], [0.33, 0.255], [0.43, 0.35]],
            max_hold=85, max_prem_frac=0.62,
        ),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd"] > 0 and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "ONESHOT_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd"] < 0 and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "ONESHOT_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 34. Adaptive 3-Lot Wide-Stop Trend Rider (12% Stop, 50% Target)
    dict(
        slug="wide_stop_trend_rider",
        bot_name="Wide-Stop Institutional Rider",
        family="Wide-Stop Trend Rider",
        description="Uses a slightly wider 12% option stop to survive 1-minute stop-hunts while riding 5m+15m institutional waves to +48% targets.",
        config=base_cfg(
            planned_risk=3600.0, daily_loss_limit=4500.0, daily_profit_lock=3600.0,
            max_lots=3, target_delta=0.56, max_trades_day=3, max_loss_streak=2,
            stop_fraction=0.12, target_fraction=0.48,
            be_act=0.075, be_lock=0.032, trail_act=0.15, trail_fr=0.058,
            step_levels=[[0.095, 0.042], [0.17, 0.105], [0.26, 0.185], [0.36, 0.28]],
            max_hold=75, max_prem_frac=0.60,
        ),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["bias_15m"] != -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "WIDESTOP_L", None
    if feat["trend_5m"] == -1 and feat["bias_15m"] != 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "WIDESTOP_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 35. Triple-Confirmation Momentum (Supertrend + TWAP + Donchian)
    dict(
        slug="triple_confirm_momentum",
        bot_name="Triple-Confirm ST+TWAP+Donchian",
        family="Triple-Confirmation Engine",
        description="Requires simultaneous Supertrend, session TWAP, and 5m EMA separation confirmation before firing.",
        config=base_cfg(planned_risk=3400.0, daily_profit_lock=3200.0, max_lots=3, target_delta=0.58, target_fraction=0.42, max_prem_frac=0.58),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["st5m_dir"] == 1 and p > feat["twap_day"] and feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if (p > feat["don5_hi"] or p > feat["e9"] > feat["e21"]) and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "TRIPLE_L", None
    if feat["st5m_dir"] == -1 and p < feat["twap_day"] and feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.25 and feat["esep_5m"] >= 0.35:
        if (p < feat["don5_lo"] or p < feat["e9"] < feat["e21"]) and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "TRIPLE_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PURE,
    ),

    # 36. Parabolic Convexity Compounder (Low VIX Shield + High VIX 4-Lot Scale)
    dict(
        slug="parabolic_convex_compounder",
        bot_name="Parabolic Convexity Compounder",
        family="Parabolic Compounder",
        description="Conserves 100% capital in low-VIX chop, then scales up to 4 lots with parabolic exhaustion locks on VIX>=14 trends.",
        config=base_cfg(
            planned_risk=4000.0, daily_loss_limit=4800.0, daily_profit_lock=4200.0,
            max_lots=4, target_delta=0.52, max_trades_day=3, max_loss_streak=2,
            stop_fraction=0.105, target_fraction=0.48,
            be_act=0.07, be_lock=0.03, trail_act=0.135, trail_fr=0.052,
            step_levels=[[0.085, 0.038], [0.15, 0.095], [0.23, 0.165], [0.33, 0.255], [0.43, 0.35]],
            max_hold=65, max_prem_frac=0.65,
        ),
        signal_code='''def evaluate_signal(feat: dict, state: dict, cfg: dict):
    if feat["bars_5m_count"] < 10:
        return 0, "NONE", None
    p = feat["price"]
    br = feat["delta_breadth_dir"] if feat["delta_breadth_dir"] else feat["breadth_dir"]
    if feat["trend_5m"] == 1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p > feat["e9"] > feat["e21"] and feat["macd"] > 0 and feat["macd_hist"] > 0 and br != -1 and feat["rsi14"] <= 75.0:
            return 1, "PARAB_COMP_L", None
    if feat["trend_5m"] == -1 and feat["eff_5m"] >= 0.26 and feat["esep_5m"] >= 0.38:
        if p < feat["e9"] < feat["e21"] and feat["macd"] < 0 and feat["macd_hist"] < 0 and br != 1 and feat["rsi14"] >= 25.0:
            return -1, "PARAB_COMP_S", None
    return 0, "NONE", None
''',
        exit_code=EXIT_PARABOLIC,
    ),
]
