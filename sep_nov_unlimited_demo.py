"""September - November 2026 Unlimited-Trades Replay (48 NSE Sessions) for the 4-Regime Micro-Scalper."""

from __future__ import annotations

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
    evaluate_all_weather_entry,
    evaluate_micro_scalp_exit,
)
from sep_nov_demo import (
    CSV_COLUMNS,
    DEMO_LOTS,
    EMERGENCY_DAILY_STOP_INR,
    LOT_SIZE,
    SLIPPAGE_PTS,
    STARTING_WALLET,
    STRATEGY_MODES,
    build_intrabar_spot_path,
    fetch_upstox_1m_candles,
    fetch_upstox_daily_anchors,
    nearest_weekly_expiry,
    price_option_leg,
    synthesize_day_1m_bars,
)

OUTPUT_CSV = os.path.join(config.BASE_DIR, "sep_nov_unlimited_demo_trades.csv")


def run_sep_nov_unlimited_demo() -> None:
    print("\n" + "=" * 156)
    print(
        "  SEPTEMBER - NOVEMBER 2026 — UNLIMITED TRADES/DAY REPLAY "
        "(₹1,00,000 WALLET | NO MAX DAILY TRADE CAP | UP TO 4 LOTS=260 QTY | -₹10,000 DAILY STOP)"
    )
    print("=" * 156)

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
        f"[DATA] Loaded {len(all_day_bars)} NSE sessions ({sorted_days[0]} to {sorted_days[-1]}) -> "
        f"Live Upstox API Days: {api_days} | Anchored Synthesis Days: {synth_days}"
    )

    wallet = STARTING_WALLET
    peak_wallet = STARTING_WALLET
    max_dd_inr = 0.0
    max_dd_pct = 0.0

    all_trades: List[Dict[str, Any]] = []
    daily_summary: List[Dict[str, Any]] = []

    entry_start_t = bot.parse_hms(config.INITIAL_ORB_END)     # 09:20:00
    entry_end_t = bot.parse_hms(config.LAST_NEW_ENTRY_TIME)   # 15:15:00

    global_trade_no = 0
    strat_short_map = {
        "TREND_PULLBACK_DIP": "PULLBACK",
        "MEAN_REVERSION_BOUNCE": "MEAN_REV",
        "VOLATILITY_SQUEEZE_IGNITION": "SQUEEZE",
        "LIQUIDITY_SWEEP_REVERSAL": "SWEEP",
    }

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
        day_strategies: Counter[str] = Counter()

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

                # 1. Manage Open Micro-Scalp Position Tick-by-Tick
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

                # 2. Evaluate All-Weather Entry (NO DAILY MAX TRADE CAP)
                if (
                    open_pos is None
                    and not day_halted
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
                    res = evaluate_all_weather_entry(
                        spot_series=spot_series,
                        contracts=active_candidates,
                        option_series_map=series_map,
                        wallet_capital=wallet,
                        lots=lots,
                        min_premium=config.MIN_OPTION_PREMIUM if dte >= 1 else 35.0,
                    )
                    while res is None and lots > 1 and wallet < 60000.0:
                        lots -= 1
                        res = evaluate_all_weather_entry(
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
                            day_strategies[strat_name] += 1
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

        used_str = ",".join(
            f"{strat_short_map[k]}({v})" for k, v in day_strategies.most_common()
        ) or "NONE"
        if day_halted:
            used_str = f"{used_str} [STOP]"

        daily_summary.append({
            "month": month_key,
            "date": day_str,
            "dow": day_label,
            "session": "Muhurat(70m)" if src_tag == "MUHURAT" else "Regular(375m)",
            "open": day_open_spot,
            "close": official_close,
            "dte": dte,
            "trades": day_trades,
            "wins": day_wins,
            "losses": day_losses,
            "strategies": used_str,
            "gross": day_gross,
            "charges": day_charges,
            "net": day_net,
            "start_wallet": day_start_wallet,
            "wallet": wallet,
            "halted": day_halted,
        })

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_trades)

    # 1. Everyday Sorted Chronological Table
    print("\n" + "-" * 156)
    print(
        f"{'Date (Day)':<16} | {'Nifty Close':>11} | {'DTE':>3} | {'Trades':>6} | {'W / L':>7} | "
        f"{'Active Strategies Used':<44} | {'Gross P&L':>13} | {'Charges':>9} | "
        f"{'Day Net P&L':>13} | {'Ending Wallet (₹)':>18}"
    )
    print("-" * 156)
    for row in daily_summary:
        date_col = f"{row['date']} ({row['dow']})"
        if row["session"] != "Regular(375m)":
            date_col = f"{row['date']} (MHT)"
        wl = f"{row['wins']}/{row['losses']}"
        print(
            f"{date_col:<16} | {row['close']:>11,.2f} | {row['dte']:>3d} | {row['trades']:>6d} | {wl:>7} | "
            f"{row['strategies']:<44} | ₹{row['gross']:>+12,.2f} | ₹{row['charges']:>8,.2f} | "
            f"₹{row['net']:>+12,.2f} | ₹{row['wallet']:>17,.2f}"
        )
    print("-" * 156)

    # 2. Monthly Summary Table
    print("\n" + "=" * 116)
    print("  MONTHLY PERFORMANCE SUMMARY (SEPTEMBER - NOVEMBER 2026 | UNLIMITED TRADES/DAY)")
    print("=" * 116)
    print(
        f"  {'Month':<14} | {'Days':>4} | {'Trades':>6} | {'W / L':>9} | {'Win %':>6} | "
        f"{'Start Wallet':>14} | {'End Wallet':>14} | {'Net P&L (₹)':>14} | {'Return %':>8}"
    )
    print("  " + "-" * 110)
    month_names = {
        "2026-09": "Sep 2026",
        "2026-10": "Oct 2026",
        "2026-11": "Nov 2026 (MTD)",
    }
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
        wl_m = f"{m_wins}/{m_losses}"
        print(
            f"  {month_names.get(m_key, m_key):<14} | {len(m_days):>4d} | {m_trades:>6d} | {wl_m:>9} | {m_wr:>5.1f}% | "
            f"₹{m_start:>13,.2f} | ₹{m_end:>13,.2f} | ₹{m_net:>+13,.2f} | {m_ret:>+7.2f}%"
        )
    print("  " + "-" * 110)

    # 3. Strategy Mode Breakdown Table
    print("\n" + "=" * 102)
    print(f"  STRATEGY MODE BREAKDOWN (SEP - NOV 2026 | UNLIMITED TRADES — {len(daily_summary)} NSE SESSIONS)")
    print("=" * 102)
    print(
        f"  {'Strategy Mode':<28} | {'Trades':>6} | {'Wins':>5} | {'Win %':>6} | "
        f"{'Gross P&L':>13} | {'Charges':>9} | {'Net Profit (₹)':>15}"
    )
    print("  " + "-" * 96)
    for strat in STRATEGY_MODES:
        subset = [t for t in all_trades if t["Strategy_Mode"] == strat]
        cnt = len(subset)
        w = sum(1 for t in subset if float(t["Net_PnL"]) > 0)
        wr = (w / cnt * 100.0) if cnt else 0.0
        g_sum = sum(float(t["Gross_PnL"]) for t in subset)
        c_sum = sum(float(t["Charges"]) for t in subset)
        n_sum = sum(float(t["Net_PnL"]) for t in subset)
        print(
            f"  {strat:<28} | {cnt:>6d} | {w:>5d} | {wr:>5.1f}% | "
            f"₹{g_sum:>+12,.2f} | ₹{c_sum:>8,.2f} | ₹{n_sum:>+14,.2f}"
        )

    total_trades = len(all_trades)
    total_wins = sum(1 for t in all_trades if float(t["Net_PnL"]) > 0)
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

    print("  " + "-" * 96)
    print(
        f"  {'TOTAL / SUMMARY':<28} | {total_trades:>6d} | {total_wins:>5d} | {win_rate:>5.1f}% | "
        f"₹{total_gross:>+12,.2f} | ₹{total_charges:>8,.2f} | ₹{total_net:>+14,.2f}"
    )
    print("=" * 102)
    print(
        f"Starting Wallet: ₹{STARTING_WALLET:,.2f} -> Ending Wallet: ₹{wallet:,.2f} "
        f"(Total Return: {ret_pct:+.2f}%) | Max Drawdown: -₹{max_dd_inr:,.2f} (-{max_dd_pct:.2f}%)"
    )
    print(
        f"Day Record     : {green_days} Green / {red_days} Red / {flat_days} Flat | "
        f"Daily Stops Hit: {halted_days} | "
        f"Best: {best_day['date']} (₹{best_day['net']:+,.2f}) | "
        f"Worst: {worst_day['date']} (₹{worst_day['net']:+,.2f})"
    )
    print(f"Exit Breakdown : {dict(exit_counts)}")
    print(f"CSV Exported   : {OUTPUT_CSV}\n")


if __name__ == "__main__":
    run_sep_nov_unlimited_demo()
