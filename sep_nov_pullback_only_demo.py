"""September - November 2026 Replay using ONLY TREND_PULLBACK_DIP (Capped 10/day & Unlimited)."""

from __future__ import annotations

import concurrent.futures
import csv
import math
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import bot
import config
from bot import (
    InstrumentSeries,
    OptionContract,
    compute_ema,
    evaluate_micro_scalp_exit,
)
from sep_nov_demo import (
    CSV_COLUMNS,
    DEMO_LOTS,
    EMERGENCY_DAILY_STOP_INR,
    LOT_SIZE,
    SLIPPAGE_PTS,
    STARTING_WALLET,
    build_intrabar_spot_path,
    fetch_upstox_1m_candles,
    fetch_upstox_daily_anchors,
    nearest_weekly_expiry,
    price_option_leg,
    synthesize_day_1m_bars,
)

CAPPED_CSV = os.path.join(config.BASE_DIR, "sep_nov_pullback_capped_trades.csv")
UNLIMITED_CSV = os.path.join(config.BASE_DIR, "sep_nov_pullback_unlimited_trades.csv")


def evaluate_pullback_only_entry(
    spot_series: InstrumentSeries,
    contracts: Dict[str, OptionContract],
    option_series_map: Dict[str, InstrumentSeries],
    wallet_capital: float,
    lots: int = 1,
    min_premium: float = 15.0,
) -> Optional[Tuple[OptionContract, float, str, Dict[str, Optional[float]]]]:
    """
    Exact TREND_PULLBACK_DIP entry engine extracted 1:1 from bot.evaluate_all_weather_entry,
    with Strategies 2, 3, and 4 disabled so ONLY TREND_PULLBACK_DIP setups trigger.
    """
    spot_ltp = spot_series.last_ltp
    if spot_ltp is None or spot_ltp <= 0 or len(spot_series.bars_1m) < 10:
        return None

    spot_ind = spot_series.get_indicators()
    spot_ema9 = spot_ind.get("ema9")
    spot_ema21 = spot_ind.get("ema21")
    spot_er10 = spot_ind.get("er10")
    spot_rsi5 = spot_ind.get("rsi5")

    if None in (spot_ema9, spot_ema21, spot_er10, spot_rsi5):
        return None
    assert spot_ema9 is not None and spot_ema21 is not None and spot_er10 is not None

    if spot_er10 < config.ER_TREND_THRESHOLD:
        return None

    matches: List[Tuple[float, OptionContract, float, str, Dict[str, Optional[float]]]] = []

    for inst_key, contract in contracts.items():
        opt_series = option_series_map.get(inst_key)
        if opt_series is None or opt_series.last_ltp is None or opt_series.last_ltp <= 0:
            continue
        opt_ltp = opt_series.last_ltp
        if opt_ltp < min_premium:
            continue
        if opt_ltp * contract.lot_size * lots > wallet_capital:
            continue
        if len(opt_series.bars_1m) < 3:
            continue

        opt_ind = opt_series.get_indicators()
        opt_ema9 = opt_ind.get("ema9")
        opt_ema21 = opt_ind.get("ema21")
        opt_vwap = opt_ind.get("vwap")
        opt_rsi5 = opt_ind.get("rsi5")
        prev_opt_rsi5 = opt_ind.get("prev_rsi5")

        if None in (opt_ema9, opt_ema21, opt_vwap, opt_rsi5) or prev_opt_rsi5 is None:
            continue
        assert opt_ema9 is not None and opt_ema21 is not None
        assert opt_vwap is not None and opt_rsi5 is not None and prev_opt_rsi5 is not None

        # Global Anti-Overextension Filter
        if (opt_ltp - opt_ema9) > config.OVEREXTENSION_MAX_PTS:
            continue

        trend_aligned = (
            (contract.option_type == "CE" and spot_ema9 > spot_ema21 and opt_ema9 > opt_ema21)
            or (contract.option_type == "PE" and spot_ema9 < spot_ema21 and opt_ema9 > opt_ema21)
        )
        if not trend_aligned:
            continue

        prev_opt_bar = opt_series.bars_1m[-1]
        cur_opt_bar = opt_series.current_1m
        opt_cur_open = cur_opt_bar.open if cur_opt_bar is not None else prev_opt_bar.close
        opt_completed = opt_series.get_1m_completed_closes()[-120:]
        prev_opt_ema9 = compute_ema(opt_completed, 9) if len(opt_completed) >= 5 else opt_ema9
        if prev_opt_ema9 is None:
            prev_opt_ema9 = opt_ema9

        pullback_dist = min(
            abs(prev_opt_bar.low - prev_opt_ema9),
            abs(prev_opt_bar.close - prev_opt_ema9),
            abs(prev_opt_bar.low - opt_vwap),
            abs(prev_opt_bar.close - opt_vwap),
        )
        if (
            pullback_dist <= 1.5
            and 35.0 <= prev_opt_rsi5 <= 62.0
            and opt_ltp > prev_opt_bar.close + 0.5
            and opt_ltp > opt_cur_open
            and opt_ltp >= opt_vwap
        ):
            sweet_bonus = 10.0 if (config.MIN_OPTION_PREMIUM <= opt_ltp <= config.MAX_OPTION_PREMIUM) else 0.0
            vwap_bonus = 3.0 if opt_ltp > opt_vwap else 0.0
            ema_dist_pen = abs(opt_ltp - opt_ema9)
            prem_dist_pen = abs(opt_ltp - 115.0) * 0.05
            rank_score = sweet_bonus + vwap_bonus - ema_dist_pen - prem_dist_pen
            matches.append((rank_score, contract, opt_ltp, "TREND_PULLBACK_DIP", opt_ind))

    if not matches:
        return None

    matches.sort(key=lambda x: x[0], reverse=True)
    _, best_c, best_ltp, best_strat, best_ind = matches[0]
    return best_c, best_ltp, best_strat, best_ind


def simulate_pullback_only(
    all_day_bars: List[Tuple[str, float, List[Tuple[datetime, float, float, float, float, float]], str]],
    max_trades_per_day: Optional[int],
    output_csv: str,
) -> Dict[str, Any]:
    wallet = STARTING_WALLET
    peak_wallet = STARTING_WALLET
    max_dd_inr = 0.0
    max_dd_pct = 0.0

    all_trades: List[Dict[str, Any]] = []
    daily_summary: List[Dict[str, Any]] = []

    entry_start_t = bot.parse_hms(config.INITIAL_ORB_END)     # 09:20:00
    entry_end_t = bot.parse_hms(config.LAST_NEW_ENTRY_TIME)   # 15:15:00

    global_trade_no = 0

    for day_str, official_close, bars, src_tag in all_day_bars:
        trade_date = datetime.strptime(day_str, "%Y-%m-%d").date()
        month_key = day_str[:7]
        day_label = trade_date.strftime("%a")
        expiry = nearest_weekly_expiry(trade_date)
        dte = max(0, (expiry - trade_date).days)
        exp_label = expiry.strftime("%d%b").upper()
        session_open_dt = bars[0][0]
        session_len_mins = max(60.0, (bars[-1][0] - bars[0][0]).total_seconds() / 60.0 + 1.0)

        day_open_spot = bars[0][1]
        day_low_spot = min(b[3] for b in bars)
        day_high_spot = max(b[2] for b in bars)
        center_strike = int(round(day_open_spot / 50.0) * 50)
        low_strike = min(center_strike - 300, int(math.floor((day_low_spot - 150.0) / 50.0) * 50))
        high_strike = max(center_strike + 300, int(math.ceil((day_high_spot + 150.0) / 50.0) * 50))
        strikes = list(range(low_strike, high_strike + 50, 50))

        contracts: Dict[str, OptionContract] = {}
        series_map: Dict[str, InstrumentSeries] = {}
        for k in strikes:
            for opt_type in ("CE", "PE"):
                key = f"NSE_FO|NIFTY_{exp_label}_{k}{opt_type}"
                sym = f"NIFTY {exp_label} {k} {opt_type}"
                contracts[key] = OptionContract(
                    instrument_key=key,
                    trading_symbol=sym,
                    strike_price=float(k),
                    option_type=opt_type,
                    expiry_date=expiry,
                    lot_size=LOT_SIZE,
                )
                series_map[key] = InstrumentSeries(key)

        spot_series = InstrumentSeries(config.SPOT_KEY)
        open_pos: Optional[Dict[str, Any]] = None
        last_exit_ts: Optional[datetime] = None
        day_halted = False
        day_start_wallet = wallet

        day_trades = 0
        day_wins = 0
        day_losses = 0
        day_gross = 0.0
        day_charges = 0.0
        day_net = 0.0

        def close_trade(
            pos: Dict[str, Any],
            raw_exit_ltp: float,
            spot_exit: float,
            exit_ts: datetime,
            reason: str,
        ) -> None:
            nonlocal wallet, peak_wallet, max_dd_inr, max_dd_pct
            nonlocal global_trade_no, day_trades, day_wins, day_losses
            nonlocal day_gross, day_charges, day_net, last_exit_ts, day_halted

            buy_px = pos["buy_price"]
            qty = pos["qty"]
            charges = pos["charges"]

            if reason == "QUICK_TARGET_HIT":
                sell_px = round(buy_px + config.INSTANT_TAKE_PROFIT_PTS, 2)
            elif reason == "DAILY_KILL_SWITCH":
                target_net = EMERGENCY_DAILY_STOP_INR - day_net
                target_gross = target_net + charges
                sell_px = max(0.05, round(buy_px + (target_gross / qty), 2))
            else:
                sell_px = max(0.05, round(raw_exit_ltp - SLIPPAGE_PTS, 2))

            pts = round(sell_px - buy_px, 2)
            gross = round(pts * qty, 2)
            net = round(gross - charges, 2)

            if reason == "DAILY_KILL_SWITCH" and (day_net + net) < EMERGENCY_DAILY_STOP_INR:
                net = round(EMERGENCY_DAILY_STOP_INR - day_net, 2)
                gross = round(net + charges, 2)
                pts = round(gross / qty, 2)
                sell_px = round(buy_px + pts, 2)

            wallet = round(wallet + net, 2)
            if wallet > peak_wallet:
                peak_wallet = wallet
            dd_inr = peak_wallet - wallet
            dd_pct = (dd_inr / peak_wallet * 100.0) if peak_wallet > 0 else 0.0
            if dd_inr > max_dd_inr:
                max_dd_inr = dd_inr
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            global_trade_no += 1
            day_trades += 1
            if net > 0:
                day_wins += 1
            else:
                day_losses += 1
            day_gross = round(day_gross + gross, 2)
            day_charges = round(day_charges + charges, 2)
            day_net = round(day_net + net, 2)
            last_exit_ts = exit_ts

            if reason == "DAILY_KILL_SWITCH" or day_net <= EMERGENCY_DAILY_STOP_INR:
                day_halted = True

            exit_reason_label = "EMERGENCY_STOP_10000" if reason == "DAILY_KILL_SWITCH" else reason
            all_trades.append({
                "Month": month_key,
                "Date": day_str,
                "Trade_No": global_trade_no,
                "Strategy_Mode": pos["strategy_name"],
                "Symbol": pos["symbol"],
                "DTE": dte,
                "Entry_Time": pos["entry_ts"].strftime("%H:%M:%S"),
                "Exit_Time": exit_ts.strftime("%H:%M:%S"),
                "Lots": pos["lots"],
                "Qty": qty,
                "Spot_Entry": f"{pos['spot_entry']:.2f}",
                "Spot_Exit": f"{spot_exit:.2f}",
                "Option_Buy": f"{buy_px:.2f}",
                "Option_Sell": f"{sell_px:.2f}",
                "Highest_LTP": f"{pos['highest_ltp']:.2f}",
                "Points": f"{pts:.2f}",
                "Gross_PnL": f"{gross:.2f}",
                "Charges": f"{charges:.2f}",
                "Net_PnL": f"{net:.2f}",
                "Day_Net_PnL": f"{day_net:.2f}",
                "Wallet_Balance": f"{wallet:.2f}",
                "Exit_Reason": exit_reason_label,
            })

        for bar_ts, o, h, l, c_px, _ in bars:
            spot_path = build_intrabar_spot_path(o, h, l, c_px)
            bar_range = max(1.0, h - l)

            for ms_off, spot_ltp in spot_path:
                tick_ts = bar_ts + timedelta(milliseconds=ms_off)
                elapsed_raw = max(0.0, (tick_ts - session_open_dt).total_seconds() / 60.0)
                mins_elapsed = elapsed_raw * (375.0 / session_len_mins)

                spot_series.on_tick(spot_ltp, tick_ts, ltq=100.0)

                opt_prices: Dict[str, float] = {}
                for key, c in contracts.items():
                    k_int = int(c.strike_price)
                    opt_ltp = price_option_leg(spot_ltp, k_int, c.option_type, dte, mins_elapsed)
                    opt_prices[key] = opt_ltp
                    dist = abs(spot_ltp - k_int)
                    sim_ltq = float(LOT_SIZE * max(1, int((bar_range * 1.5) * math.exp(-dist / 220.0))))
                    series_map[key].on_tick(opt_ltp, tick_ts, ltq=sim_ltq)

                t_now = tick_ts.time()

                # 1. Manage Open Micro-Scalp Position
                if open_pos is not None:
                    cur_ltp = opt_prices[open_pos["key"]]
                    minutes_held = (tick_ts - open_pos["entry_ts"]).total_seconds() / 60.0

                    new_high, new_sl, exit_reason, target_px = evaluate_micro_scalp_exit(
                        entry_price=open_pos["buy_price"],
                        current_ltp=cur_ltp,
                        highest_ltp=open_pos["highest_ltp"],
                        sl_price=open_pos["sl_price"],
                        minutes_held=minutes_held,
                        ts_time=t_now,
                        realized_day_net_pnl=day_net,
                        qty=open_pos["qty"],
                        charges=open_pos["charges"],
                        max_daily_loss_inr=EMERGENCY_DAILY_STOP_INR,
                    )
                    open_pos["highest_ltp"] = new_high
                    open_pos["sl_price"] = new_sl

                    if exit_reason is not None:
                        exit_ltp = target_px if (exit_reason == "QUICK_TARGET_HIT" and target_px) else cur_ltp
                        close_trade(open_pos, exit_ltp, spot_ltp, tick_ts, exit_reason)
                        open_pos = None

                # 2. Evaluate TREND_PULLBACK_DIP ONLY Entry
                cap_ok = max_trades_per_day is None or day_trades < max_trades_per_day
                if (
                    open_pos is None
                    and not day_halted
                    and cap_ok
                    and day_net > EMERGENCY_DAILY_STOP_INR
                    and entry_start_t <= t_now < entry_end_t
                ):
                    cooldown_ok = (
                        last_exit_ts is None
                        or (tick_ts - last_exit_ts).total_seconds() >= config.REENTRY_COOLDOWN_SECS
                    )
                    if not cooldown_ok:
                        continue

                    spot_atm = int(round(spot_ltp / 50.0) * 50)
                    active_candidates: Dict[str, OptionContract] = {}
                    for key, c in contracts.items():
                        k_int = int(c.strike_price)
                        if (
                            (c.option_type == "CE" and k_int in (spot_atm, spot_atm - 50))
                            or (c.option_type == "PE" and k_int in (spot_atm, spot_atm + 50))
                        ):
                            active_candidates[key] = c

                    lots = DEMO_LOTS
                    res = evaluate_pullback_only_entry(
                        spot_series=spot_series,
                        contracts=active_candidates,
                        option_series_map=series_map,
                        wallet_capital=wallet,
                        lots=lots,
                        min_premium=config.MIN_OPTION_PREMIUM if dte >= 1 else 35.0,
                    )
                    while res is None and lots > 1 and wallet < 60000.0:
                        lots -= 1
                        res = evaluate_pullback_only_entry(
                            spot_series=spot_series,
                            contracts=active_candidates,
                            option_series_map=series_map,
                            wallet_capital=wallet,
                            lots=lots,
                            min_premium=35.0,
                        )

                    if res is not None:
                        best_c, entry_ltp, strat_name, _ = res
                        buy_px = round(entry_ltp + SLIPPAGE_PTS, 2)
                        qty = LOT_SIZE * lots
                        if buy_px * qty <= wallet:
                            charges = round(config.FLAT_BROKERAGE_ROUND + config.STATUTORY_TAX_PER_LOT * lots, 2)
                            open_pos = {
                                "key": best_c.instrument_key,
                                "symbol": best_c.trading_symbol,
                                "strategy_name": strat_name,
                                "entry_ts": tick_ts,
                                "lots": lots,
                                "qty": qty,
                                "spot_entry": spot_ltp,
                                "buy_price": buy_px,
                                "highest_ltp": entry_ltp,
                                "sl_price": round(buy_px - config.INITIAL_SL_PTS, 2),
                                "charges": charges,
                            }

        if open_pos is not None:
            last_bar = bars[-1]
            last_ts = last_bar[0] + timedelta(seconds=50)
            last_spot = last_bar[4]
            elapsed_raw = max(0.0, (last_ts - session_open_dt).total_seconds() / 60.0)
            mins_e = elapsed_raw * (375.0 / session_len_mins)
            c_obj = contracts[open_pos["key"]]
            last_ltp = price_option_leg(last_spot, int(c_obj.strike_price), c_obj.option_type, dte, mins_e)
            close_trade(open_pos, last_ltp, last_spot, last_ts, "HARD_SQUARE_OFF")
            open_pos = None

        ce_cnt = sum(1 for t in all_trades if t["Date"] == day_str and t["Symbol"].endswith("CE"))
        pe_cnt = sum(1 for t in all_trades if t["Date"] == day_str and t["Symbol"].endswith("PE"))
        status_note = f"CE({ce_cnt})/PE({pe_cnt})"
        if day_halted:
            status_note = f"{status_note} [STOP]"

        daily_summary.append({
            "month": month_key,
            "date": day_str,
            "dow": day_label,
            "session": "Muhurat(70m)" if src_tag == "MUHURAT" else "Regular(375m)",
            "close": official_close,
            "dte": dte,
            "trades": day_trades,
            "wins": day_wins,
            "losses": day_losses,
            "note": status_note,
            "gross": day_gross,
            "charges": day_charges,
            "net": day_net,
            "start_wallet": day_start_wallet,
            "wallet": wallet,
            "halted": day_halted,
        })

    with open(output_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_trades)

    return {
        "max_trades_per_day": max_trades_per_day,
        "output_csv": output_csv,
        "daily_summary": daily_summary,
        "all_trades": all_trades,
        "ending_wallet": wallet,
        "max_dd_inr": max_dd_inr,
        "max_dd_pct": max_dd_pct,
    }


def print_report(title: str, res: Dict[str, Any]) -> None:
    daily_summary = res["daily_summary"]
    all_trades = res["all_trades"]
    wallet = res["ending_wallet"]

    print("\n" + "=" * 134)
    print(f"  {title}")
    print("=" * 134)
    print(
        f"{'Date (Day)':<16} | {'Nifty Close':>11} | {'DTE':>3} | {'Trades':>6} | {'W / L':>7} | "
        f"{'Direction Split':<20} | {'Gross P&L':>13} | {'Charges':>9} | "
        f"{'Day Net P&L':>13} | {'Ending Wallet (₹)':>18}"
    )
    print("-" * 134)
    for row in daily_summary:
        date_col = f"{row['date']} (MHT)" if row["session"] != "Regular(375m)" else f"{row['date']} ({row['dow']})"
        wl = f"{row['wins']}/{row['losses']}"
        print(
            f"{date_col:<16} | {row['close']:>11,.2f} | {row['dte']:>3d} | {row['trades']:>6d} | {wl:>7} | "
            f"{row['note']:<20} | ₹{row['gross']:>+12,.2f} | ₹{row['charges']:>8,.2f} | "
            f"₹{row['net']:>+12,.2f} | ₹{row['wallet']:>17,.2f}"
        )
    print("-" * 134)

    print("\n" + "-" * 110)
    print(
        f"  {'Month':<14} | {'Days':>4} | {'Trades':>6} | {'W / L':>9} | {'Win %':>6} | "
        f"{'Start Wallet':>14} | {'End Wallet':>14} | {'Net P&L (₹)':>14} | {'Return %':>8}"
    )
    print("  " + "-" * 106)
    month_names = {"2026-09": "Sep 2026", "2026-10": "Oct 2026", "2026-11": "Nov 2026 (MTD)"}
    for m_key in sorted({r["month"] for r in daily_summary}):
        m_days = [r for r in daily_summary if r["month"] == m_key]
        m_trades = sum(r["trades"] for r in m_days)
        m_wins = sum(r["wins"] for r in m_days)
        m_losses = sum(r["losses"] for r in m_days)
        m_wr = (m_wins / m_trades * 100.0) if m_trades else 0.0
        m_start = m_days[0]["start_wallet"]
        m_end = m_days[-1]["wallet"]
        m_net = sum(r["net"] for r in m_days)
        m_ret = (m_net / m_start * 100.0) if m_start > 0 else 0.0
        print(
            f"  {month_names.get(m_key, m_key):<14} | {len(m_days):>4d} | {m_trades:>6d} | "
            f"{f'{m_wins}/{m_losses}':>9} | {m_wr:>5.1f}% | ₹{m_start:>13,.2f} | ₹{m_end:>13,.2f} | "
            f"₹{m_net:>+13,.2f} | {m_ret:>+7.2f}%"
        )

    total_trades = len(all_trades)
    total_wins = sum(1 for t in all_trades if float(t["Net_PnL"]) > 0)
    total_losses = total_trades - total_wins
    win_rate = (total_wins / total_trades * 100.0) if total_trades else 0.0
    total_gross = sum(float(t["Gross_PnL"]) for t in all_trades)
    total_charges = sum(float(t["Charges"]) for t in all_trades)
    total_net = sum(float(t["Net_PnL"]) for t in all_trades)
    ret_pct = ((wallet - STARTING_WALLET) / STARTING_WALLET) * 100.0

    green_days = sum(1 for r in daily_summary if r["net"] > 0)
    red_days = sum(1 for r in daily_summary if r["net"] < 0)
    flat_days = len(daily_summary) - green_days - red_days
    halted_days = sum(1 for r in daily_summary if r["halted"])
    best_day = max(daily_summary, key=lambda r: r["net"])
    worst_day = min(daily_summary, key=lambda r: r["net"])
    exit_counts = Counter(t["Exit_Reason"] for t in all_trades)

    print("  " + "-" * 106)
    print(
        f"  {'TOTAL (PULLBACK)':<14} | {len(daily_summary):>4d} | {total_trades:>6d} | "
        f"{f'{total_wins}/{total_losses}':>9} | {win_rate:>5.1f}% | ₹{STARTING_WALLET:>13,.2f} | "
        f"₹{wallet:>13,.2f} | ₹{total_net:>+13,.2f} | {ret_pct:>+7.2f}%"
    )
    print("-" * 110)
    print(
        f"Gross P&L: ₹{total_gross:+,.2f} | Charges: ₹{total_charges:,.2f} | "
        f"Net P&L: ₹{total_net:+,.2f} | Max DD: -₹{res['max_dd_inr']:,.2f} (-{res['max_dd_pct']:.2f}%)"
    )
    print(
        f"Day Record: {green_days} Green / {red_days} Red / {flat_days} Flat | "
        f"Daily Stops Hit: {halted_days} | "
        f"Best: {best_day['date']} (₹{best_day['net']:+,.2f}) | "
        f"Worst: {worst_day['date']} (₹{worst_day['net']:+,.2f})"
    )
    print(f"Exit Breakdown: {dict(exit_counts)}")
    print(f"CSV Exported  : {res['output_csv']}\n")


def main() -> None:
    api_bars_by_day = fetch_upstox_1m_candles()
    daily_anchors = fetch_upstox_daily_anchors()

    all_dates_map: Dict[str, float] = {}
    for d_str, d_bars in api_bars_by_day.items():
        all_dates_map[d_str] = d_bars[-1][4]
    for d_str, d_close in daily_anchors:
        if d_str not in all_dates_map:
            all_dates_map[d_str] = d_close

    sorted_days = sorted(all_dates_map.keys())
    if not sorted_days:
        raise RuntimeError("No historical NIFTY 50 candles returned by Upstox API for Sep-Nov 2026.")

    api_days = 0
    synth_days = 0
    all_day_bars: List[Tuple[str, float, List[Tuple[datetime, float, float, float, float, float]], str]] = []
    prev_close = all_dates_map[sorted_days[0]]

    for idx, day_str in enumerate(sorted_days):
        official_close = all_dates_map[day_str]
        if day_str in api_bars_by_day:
            bars = api_bars_by_day[day_str]
            api_days += 1
            src_tag = "MUHURAT" if len(bars) < 300 else "LIVE_1M"
        else:
            bars = synthesize_day_1m_bars(day_str, prev_close, official_close, idx)
            synth_days += 1
            src_tag = "SYNTH"
        all_day_bars.append((day_str, official_close, bars, src_tag))
        prev_close = official_close

    print(
        f"\n[DATA] Loaded {len(all_day_bars)} NSE sessions ({sorted_days[0]} to {sorted_days[-1]}) -> "
        f"Live Upstox API Days: {api_days} | Anchored Synthesis Days: {synth_days}"
    )

    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        fut_capped = pool.submit(simulate_pullback_only, all_day_bars, config.MAX_TRADES_PER_DAY, CAPPED_CSV)
        fut_unlim = pool.submit(simulate_pullback_only, all_day_bars, None, UNLIMITED_CSV)
        res_capped = fut_capped.result()
        res_unlim = fut_unlim.result()

    print_report(
        "TREND_PULLBACK_DIP ONLY — CAPPED (10 TRADES/DAY | ₹1,00,000 WALLET | 4 LOTS=260 QTY | -₹10,000 DAILY STOP)",
        res_capped,
    )
    print_report(
        "TREND_PULLBACK_DIP ONLY — UNLIMITED (NO TRADE CAP | ₹1,00,000 WALLET | 4 LOTS=260 QTY | -₹10,000 DAILY STOP)",
        res_unlim,
    )


if __name__ == "__main__":
    main()
