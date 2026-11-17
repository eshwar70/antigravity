"""Unrestricted October 2026 (20 Trading Days) Live Replay with ₹50,000 Wallet & 14-Strike Option Chain."""

from __future__ import annotations

import csv
import math
import os
import random
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pytz
import requests

import bot
import config
from bot import InstrumentSeries, ORBTracker, OptionContract

IST = pytz.timezone(config.TIMEZONE)

OUTPUT_CSV = os.path.join(config.BASE_DIR, "october_50k_unrestricted_trades.csv")

STARTING_WALLET = 50000.0
LOT_SIZE = 65
MIN_LOTS = 1
MAX_LOTS = 5
WALLET_ALLOCATION_PCT = 0.45
MIN_OPTION_PREMIUM = 15.0
REENTRY_COOLDOWN_SECS = 0
SLIPPAGE_PTS = 0.20

INITIAL_SL_PTS = 12.0
TRAIL_STEP_1_PTS = 10.0
TRAIL_STEP_2_PTS = 15.0
TRAIL_DYNAMIC_PTS = 22.0
TRAIL_DYNAMIC_GAP = 6.0
THETA_TIME_STOP_MINS = 25.0
THETA_MIN_PROFIT_PTS = 5.0

REVERSAL_MIN_MINS = 10.0
REVERSAL_MAX_GAIN_PTS = 8.0

FLAT_BROKERAGE_ROUND = 40.0
STATUTORY_TAX_PER_LOT = 15.0

ENTRY_START_STR = "09:20:00"
ENTRY_END_STR = "15:25:00"
EOD_SQUAREOFF_STR = "15:28:00"

OCTOBER_2026_TRADING_DAYS: List[Tuple[str, float]] = [
    ("2026-10-01", 22421.95),
    ("2026-10-05", 22555.75),
    ("2026-10-06", 22776.10),
    ("2026-10-07", 22603.05),
    ("2026-10-08", 22231.80),
    ("2026-10-09", 22520.45),
    ("2026-10-12", 22363.35),
    ("2026-10-13", 22721.95),
    ("2026-10-14", 22622.70),
    ("2026-10-15", 22997.35),
    ("2026-10-16", 23146.15),
    ("2026-10-19", 22888.95),
    ("2026-10-21", 22811.35),
    ("2026-10-22", 22687.65),
    ("2026-10-23", 22600.00),
    ("2026-10-26", 22753.20),
    ("2026-10-27", 22749.75),
    ("2026-10-28", 22698.85),
    ("2026-10-29", 22936.75),
    ("2026-10-30", 23053.10),
]

WEEKLY_EXPIRIES: List[date] = [
    date(2026, 10, 6),
    date(2026, 10, 13),
    date(2026, 10, 19),  # Monday expiry due to Oct 20 Dussehra holiday
    date(2026, 10, 27),
    date(2026, 11, 3),
]

CSV_COLUMNS = [
    "Date",
    "Trade_No",
    "Symbol",
    "Strike_Type",
    "Entry_Time",
    "Exit_Time",
    "Lots",
    "Qty",
    "Spot_Entry",
    "Spot_Exit",
    "Option_Buy",
    "Option_Sell",
    "Highest_LTP",
    "Points",
    "Gross_PnL",
    "Charges",
    "Net_PnL",
    "Running_Wallet",
    "Exit_Reason",
]


def nearest_weekly_expiry(trade_date: date) -> date:
    for exp in WEEKLY_EXPIRIES:
        if exp >= trade_date:
            return exp
    return WEEKLY_EXPIRIES[-1]


def fetch_upstox_1m_candles() -> Dict[str, List[Tuple[datetime, float, float, float, float, float]]]:
    """Fetch 1-min Nifty 50 Spot candles from Upstox V2 Historical API across Oct 2026."""
    by_day: Dict[str, List[Tuple[datetime, float, float, float, float, float]]] = defaultdict(list)
    chunks = [
        ("2026-10-01", "2026-10-09"),
        ("2026-10-12", "2026-10-19"),
        ("2026-10-21", "2026-10-30"),
    ]
    headers = {"Accept": "application/json"}

    for from_d, to_d in chunks:
        url = f"https://api.upstox.com/v2/historical-candle/NSE_INDEX%7CNifty%2050/1minute/{to_d}/{from_d}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue
            raw_candles = ((resp.json().get("data") or {}).get("candles")) or []
            for row in raw_candles:
                if not isinstance(row, (list, tuple)) or len(row) < 6:
                    continue
                dt = datetime.fromisoformat(str(row[0]))
                dt = IST.localize(dt) if dt.tzinfo is None else dt.astimezone(IST)
                day_str = dt.strftime("%Y-%m-%d")
                by_day[day_str].append(
                    (dt, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5] or 0.0))
                )
        except Exception:
            continue

    for day_str in list(by_day.keys()):
        bars = sorted(by_day[day_str], key=lambda x: x[0])
        # Keep regular NSE market hours 09:15 - 15:29
        bars = [
            b
            for b in bars
            if (9, 15) <= (b[0].hour, b[0].minute) <= (15, 29)
        ]
        if len(bars) >= 300:
            by_day[day_str] = bars
        else:
            del by_day[day_str]

    return by_day


def synthesize_day_1m_bars(
    day_str: str,
    prev_close: float,
    official_close: float,
    seed_idx: int,
) -> List[Tuple[datetime, float, float, float, float, float]]:
    """
    Generate realistic 375 1-minute Spot OHLCV bars (09:15–15:29 IST) anchored to the
    official closing level with realistic opening gap, ORB structure, and intraday swings.
    """
    rng = random.Random(20261000 + seed_idx * 97)
    d = datetime.strptime(day_str, "%Y-%m-%d").date()
    start_dt = IST.localize(datetime(d.year, d.month, d.day, 9, 15, 0))

    total_move = official_close - prev_close
    gap = total_move * 0.30 + rng.uniform(-35.0, 35.0)
    day_open = round(prev_close + gap, 2)

    # Construct an intraday regime path via 375 Brownian-bridge increments + swing wave
    n = 375
    steps = np.zeros(n, dtype=float)
    # Two intraday swing waves + micro volatility
    phase1 = rng.uniform(0, 2 * math.pi)
    phase2 = rng.uniform(0, 2 * math.pi)
    amp1 = rng.uniform(25.0, 65.0) * rng.choice([-1.0, 1.0])
    amp2 = rng.uniform(15.0, 40.0) * rng.choice([-1.0, 1.0])

    raw_walk = np.zeros(n + 1, dtype=float)
    vol_regime = 5.5 + min(4.5, abs(total_move) / 70.0)
    for idx in range(1, n + 1):
        # Slightly higher volatility during opening 30m and final 45m
        mult = 1.35 if idx < 30 or idx > 330 else 0.90
        wave = (
            amp1 * math.sin(2.0 * math.pi * idx / n + phase1)
            + amp2 * math.sin(4.0 * math.pi * idx / n + phase2)
        ) / n * 4.0
        raw_walk[idx] = raw_walk[idx - 1] + rng.gauss(0.0, vol_regime * mult) + wave

    # Bridge raw_walk so raw_walk[0] == day_open and raw_walk[n] == official_close
    end_drift = (official_close - day_open) - raw_walk[n]
    closes = np.array([
        day_open + raw_walk[i] + end_drift * (i / n)
        for i in range(1, n + 1)
    ])
    closes[-1] = official_close

    bars: List[Tuple[datetime, float, float, float, float, float]] = []
    cur_open = day_open
    for i in range(n):
        ts = start_dt + timedelta(minutes=i)
        c = round(float(closes[i]), 2)
        o = round(float(cur_open), 2)
        wick_up = abs(rng.gauss(0.0, 2.8)) + 0.8
        wick_dn = abs(rng.gauss(0.0, 2.8)) + 0.8
        h = round(max(o, c) + wick_up, 2)
        l = round(min(o, c) - wick_dn, 2)
        bars.append((ts, o, h, l, c, 0.0))
        cur_open = c

    return bars


def price_option_chain(
    spot_ltp: float,
    strikes: List[int],
    dte: int,
    mins_elapsed: float,
) -> Dict[Tuple[int, str], float]:
    sqrt_dte = math.sqrt(max(0.3, float(dte)))
    decay_den = max(1.0, float(dte))
    time_decay = 1.0 - 0.35 * (mins_elapsed / 375.0) / decay_den

    prices: Dict[Tuple[int, str], float] = {}
    for k in strikes:
        intrinsic_ce = max(0.0, spot_ltp - k)
        intrinsic_pe = max(0.0, k - spot_ltp)
        moneyness_dist = abs(spot_ltp - k)
        time_val = max(
            2.0,
            (68.0 + 15.0 * sqrt_dte) * math.exp(-moneyness_dist / 160.0) * time_decay,
        )
        prices[(k, "CE")] = round(max(0.5, intrinsic_ce + time_val), 1)
        prices[(k, "PE")] = round(max(0.5, intrinsic_pe + time_val), 1)
    return prices


def classify_strike_type(strike: int, option_type: str, spot_entry: float) -> str:
    atm = int(round(spot_entry / 50.0) * 50)
    if strike == atm:
        return f"ATM {option_type}"
    if option_type == "CE":
        return f"{'ITM' if strike < atm else 'OTM'} CE"
    return f"{'ITM' if strike > atm else 'OTM'} PE"


def run_replay() -> None:
    print("\n" + "=" * 96)
    print("  OCTOBER 2026 UNRESTRICTED MULTI-STRIKE REPLAY (20 NSE TRADING DAYS | ₹50,000 WALLET)")
    print("=" * 96)

    api_bars_by_day = fetch_upstox_1m_candles()
    api_days_count = 0
    synth_days_count = 0

    all_day_bars: List[Tuple[str, float, str, List[Tuple[datetime, float, float, float, float, float]]]] = []
    prev_close = 22360.0
    for idx, (day_str, official_close) in enumerate(OCTOBER_2026_TRADING_DAYS):
        if day_str in api_bars_by_day:
            bars = api_bars_by_day[day_str]
            src = "UPSTOX_API"
            api_days_count += 1
        else:
            bars = synthesize_day_1m_bars(day_str, prev_close, official_close, idx)
            src = "SYNTH_ANCHORED"
            synth_days_count += 1
        all_day_bars.append((day_str, official_close, src, bars))
        prev_close = official_close

    print(
        f"[DATA] Loaded 20 NSE trading days -> Live Upstox API Days: {api_days_count} | "
        f"Anchored 1-Min Synthesis Days: {synth_days_count}"
    )

    wallet = STARTING_WALLET
    all_trades: List[Dict[str, Any]] = []
    daily_summary: List[Dict[str, Any]] = []

    entry_start_t = bot.parse_hms(ENTRY_START_STR)
    entry_end_t = bot.parse_hms(ENTRY_END_STR)
    eod_sq_t = bot.parse_hms(EOD_SQUAREOFF_STR)

    global_trade_no = 0

    for day_str, official_close, data_src, bars in all_day_bars:
        trade_date = datetime.strptime(day_str, "%Y-%m-%d").date()
        expiry = nearest_weekly_expiry(trade_date)
        dte = max(0, (expiry - trade_date).days)
        exp_label = expiry.strftime("%d%b").upper()
        market_open_dt = IST.localize(datetime(trade_date.year, trade_date.month, trade_date.day, 9, 15, 0))

        day_open_spot = bars[0][1]
        center_strike = int(round(day_open_spot / 50.0) * 50)
        strikes = [center_strike + offset for offset in (-150, -100, -50, 0, 50, 100, 150)]

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

        orb = ORBTracker()
        spot_series = InstrumentSeries(config.SPOT_KEY)

        open_pos: Optional[Dict[str, Any]] = None
        last_exit_bucket_1m: Optional[datetime] = None

        day_trades = 0
        day_wins = 0
        day_losses = 0
        day_lots = 0
        day_gross = 0.0
        day_charges = 0.0
        day_net = 0.0
        day_option_pnl: Counter[str] = Counter()
        day_option_counts: Counter[str] = Counter()

        def close_trade(
            pos: Dict[str, Any],
            exit_ltp: float,
            spot_exit: float,
            exit_ts: datetime,
            reason: str,
        ) -> None:
            nonlocal wallet, global_trade_no, day_trades, day_wins, day_losses
            nonlocal day_lots, day_gross, day_charges, day_net, last_exit_bucket_1m

            sell_px = max(0.05, round(exit_ltp - SLIPPAGE_PTS, 2))
            buy_px = pos["buy_price"]
            lots = pos["lots"]
            qty = pos["qty"]
            pts = round(sell_px - buy_px, 2)
            gross = round(pts * qty, 2)
            charges = round(FLAT_BROKERAGE_ROUND + STATUTORY_TAX_PER_LOT * lots, 2)
            net = round(gross - charges, 2)

            wallet = round(wallet + net, 2)
            global_trade_no += 1
            day_trades += 1
            if net > 0:
                day_wins += 1
            else:
                day_losses += 1
            day_lots += lots
            day_gross = round(day_gross + gross, 2)
            day_charges = round(day_charges + charges, 2)
            day_net = round(day_net + net, 2)
            day_option_pnl[pos["symbol"]] += net
            day_option_counts[pos["symbol"]] += 1
            last_exit_bucket_1m = exit_ts.replace(second=0, microsecond=0)

            all_trades.append({
                "Date": day_str,
                "Trade_No": global_trade_no,
                "Symbol": pos["symbol"],
                "Strike_Type": pos["strike_type"],
                "Entry_Time": pos["entry_ts"].strftime("%H:%M:%S"),
                "Exit_Time": exit_ts.strftime("%H:%M:%S"),
                "Lots": lots,
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
                "Running_Wallet": f"{wallet:.2f}",
                "Exit_Reason": reason,
            })

        def find_best_signal(
            spot_ltp: float,
            opt_prices: Dict[Tuple[int, str], float],
            required_type: Optional[str] = None,
            strong_only: bool = False,
        ) -> Optional[Tuple[float, str, float, str]]:
            best: Optional[Tuple[float, str, float, str]] = None
            for key, c in contracts.items():
                if required_type and c.option_type != required_type:
                    continue
                k_int = int(c.strike_price)
                opt_ltp = opt_prices[(k_int, c.option_type)]
                if opt_ltp < MIN_OPTION_PREMIUM:
                    continue
                if opt_ltp * LOT_SIZE > wallet:
                    continue

                series = series_map[key]
                ind = series.get_indicators()
                vwap = ind["vwap"]
                ema9 = ind["ema9"]
                ema21 = ind["ema21"]
                rsi14 = ind["rsi14"]
                if None in (vwap, ema9, ema21, rsi14):
                    continue
                assert vwap is not None and ema9 is not None and ema21 is not None and rsi14 is not None

                reason: Optional[str] = None

                # 1. ORB Breakout / Breakdown
                if orb.orb_ready and orb.orb_high is not None and orb.orb_low is not None:
                    if c.option_type == "CE" and spot_ltp > orb.orb_high:
                        if opt_ltp > vwap and ema9 > ema21 and 54.0 <= rsi14 <= 85.0:
                            if not strong_only or rsi14 >= 60.0:
                                reason = "ORB_BREAKOUT"
                    elif c.option_type == "PE" and spot_ltp < orb.orb_low:
                        if opt_ltp > vwap and ema9 > ema21 and 54.0 <= rsi14 <= 85.0:
                            if not strong_only or rsi14 >= 60.0:
                                reason = "ORB_BREAKDOWN"

                # 2. Intraday Momentum Surge / Reversal Flip (3m/5m High + Expansion)
                if reason is None and len(series.bars_1m) >= 5 and series.current_1m is not None:
                    prev_3m_high = max(b.high for b in list(series.bars_1m)[-3:])
                    prev_5m_high = series.bars_5m[-1].high if len(series.bars_5m) >= 1 else prev_3m_high
                    ref_high = min(prev_3m_high, prev_5m_high) if len(series.bars_5m) >= 1 else prev_3m_high
                    avg_body = float(np.mean([b.body for b in list(series.bars_1m)[-5:]]))
                    cur_1m = series.current_1m
                    if (
                        opt_ltp > ref_high
                        and opt_ltp > vwap
                        and ema9 > ema21
                        and rsi14 >= 58.0
                        and cur_1m.close > cur_1m.open
                        and avg_body > 0.0
                        and cur_1m.body > 1.15 * avg_body
                    ):
                        reason = "MOMENTUM_SURGE"

                if reason is not None:
                    score = rsi14 * (opt_ltp / vwap)
                    if best is None or score > best[0]:
                        best = (score, key, opt_ltp, reason)
            return best

        def open_trade(key: str, opt_ltp: float, spot_ltp: float, ts: datetime) -> Optional[Dict[str, Any]]:
            c = contracts[key]
            buy_px = round(opt_ltp + SLIPPAGE_PTS, 2)
            lots = max(MIN_LOTS, min(MAX_LOTS, int((wallet * WALLET_ALLOCATION_PCT) // (buy_px * LOT_SIZE))))
            if buy_px * LOT_SIZE * lots > wallet:
                lots = max(MIN_LOTS, int(wallet // (buy_px * LOT_SIZE)))
            if lots < 1 or buy_px * LOT_SIZE > wallet:
                return None
            qty = lots * LOT_SIZE
            return {
                "key": key,
                "symbol": c.trading_symbol,
                "option_type": c.option_type,
                "strike_type": classify_strike_type(int(c.strike_price), c.option_type, spot_ltp),
                "entry_ts": ts,
                "lots": lots,
                "qty": qty,
                "spot_entry": spot_ltp,
                "buy_price": buy_px,
                "highest_ltp": opt_ltp,
                "sl_price": round(buy_px - INITIAL_SL_PTS, 2),
                "trailed": False,
            }

        # Stream 4 live ticks per 1-minute bar
        for bar_ts, o, h, l, c_px, _ in bars:
            spot_ticks = (o, l, h, c_px) if c_px >= o else (o, h, l, c_px)
            bar_range = max(1.0, h - l)

            for sub_idx, spot_ltp in enumerate(spot_ticks):
                tick_ts = bar_ts + timedelta(seconds=sub_idx * 15)
                mins_elapsed = max(0.0, (tick_ts - market_open_dt).total_seconds() / 60.0)

                spot_series.on_tick(spot_ltp, tick_ts)
                orb.on_spot_tick(spot_ltp, tick_ts)
                orb.refresh_state(tick_ts.time())

                opt_prices = price_option_chain(spot_ltp, strikes, dte, mins_elapsed)

                # Feed live tick into all 14 option series
                for key, contract in contracts.items():
                    k_int = int(contract.strike_price)
                    opt_ltp = opt_prices[(k_int, contract.option_type)]
                    dist = abs(spot_ltp - k_int)
                    sim_ltq = float(LOT_SIZE * max(1, int((bar_range * 1.5) * math.exp(-dist / 220.0))))
                    series_map[key].on_tick(opt_ltp, tick_ts, ltq=sim_ltq)

                t_now = tick_ts.time()

                # Manage Open Trade Tick-by-Tick
                if open_pos is not None:
                    pos_c = contracts[open_pos["key"]]
                    cur_opt_ltp = opt_prices[(int(pos_c.strike_price), pos_c.option_type)]

                    if cur_opt_ltp > open_pos["highest_ltp"]:
                        open_pos["highest_ltp"] = cur_opt_ltp

                    buy_px = open_pos["buy_price"]
                    gain_high = open_pos["highest_ltp"] - buy_px
                    points_gain = cur_opt_ltp - buy_px
                    sl = open_pos["sl_price"]

                    if gain_high >= TRAIL_STEP_1_PTS:
                        new_sl = round(buy_px - 4.0, 2)
                        if new_sl > sl:
                            sl = new_sl
                            open_pos["trailed"] = True
                    if gain_high >= TRAIL_STEP_2_PTS:
                        new_sl = round(buy_px + 10.0, 2)
                        if new_sl > sl:
                            sl = new_sl
                            open_pos["trailed"] = True
                    if gain_high >= TRAIL_DYNAMIC_PTS:
                        new_sl = round(open_pos["highest_ltp"] - TRAIL_DYNAMIC_GAP, 1)
                        if new_sl > sl:
                            sl = new_sl
                            open_pos["trailed"] = True
                    open_pos["sl_price"] = sl

                    elapsed_mins = (tick_ts - open_pos["entry_ts"]).total_seconds() / 60.0

                    exit_reason: Optional[str] = None
                    if t_now >= eod_sq_t:
                        exit_reason = "HARD_SQUARE_OFF"
                    elif cur_opt_ltp <= sl:
                        exit_reason = "TRAILING_SL" if open_pos["trailed"] else "STOP_LOSS"
                    elif elapsed_mins >= THETA_TIME_STOP_MINS and points_gain < THETA_MIN_PROFIT_PTS:
                        exit_reason = "THETA_TIME_STOP"

                    if exit_reason is not None:
                        close_trade(open_pos, cur_opt_ltp, spot_ltp, tick_ts, exit_reason)
                        open_pos = None
                    elif (
                        elapsed_mins >= REVERSAL_MIN_MINS
                        and points_gain < REVERSAL_MAX_GAIN_PTS
                        and entry_start_t <= t_now <= entry_end_t
                    ):
                        opp_type = "PE" if open_pos["option_type"] == "CE" else "CE"
                        flip = find_best_signal(spot_ltp, opt_prices, required_type=opp_type, strong_only=True)
                        if flip is not None:
                            _, flip_key, flip_ltp, _ = flip
                            close_trade(open_pos, cur_opt_ltp, spot_ltp, tick_ts, "REVERSAL_FLIP")
                            open_pos = open_trade(flip_key, flip_ltp, spot_ltp, tick_ts)

                # Evaluate New Entry if Flat
                if open_pos is None and entry_start_t <= t_now <= entry_end_t:
                    cur_bucket = tick_ts.replace(second=0, microsecond=0)
                    can_enter = (last_exit_bucket_1m is None) or (cur_bucket > last_exit_bucket_1m)
                    if can_enter:
                        sig = find_best_signal(spot_ltp, opt_prices)
                        if sig is not None:
                            _, sig_key, sig_ltp, _ = sig
                            open_pos = open_trade(sig_key, sig_ltp, spot_ltp, tick_ts)

        # Safety force-close if somehow still open at end of bars
        if open_pos is not None:
            last_bar = bars[-1]
            last_ts = last_bar[0] + timedelta(seconds=45)
            last_spot = last_bar[4]
            last_prices = price_option_chain(
                last_spot, strikes, dte, (last_ts - market_open_dt).total_seconds() / 60.0
            )
            pos_c = contracts[open_pos["key"]]
            close_trade(
                open_pos,
                last_prices[(int(pos_c.strike_price), pos_c.option_type)],
                last_spot,
                last_ts,
                "HARD_SQUARE_OFF",
            )
            open_pos = None

        top_opt = "NONE"
        if day_option_pnl:
            top_opt = max(day_option_pnl.items(), key=lambda kv: (kv[1], day_option_counts[kv[0]]))[0]

        daily_summary.append({
            "date": day_str,
            "close": official_close,
            "trades": day_trades,
            "wins": day_wins,
            "losses": day_losses,
            "lots": day_lots,
            "top_opt": top_opt,
            "gross": day_gross,
            "charges": day_charges,
            "net": day_net,
            "wallet": wallet,
        })

    # Export Trades CSV
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_trades)

    # Print 20-Day October 2026 Performance Table
    print("\n" + "-" * 136)
    print(
        f"{'Date':<10} | {'Nifty Close':>11} | {'Trades':>6} | {'W / L':>7} | {'Lots':>4} | "
        f"{'Top Option Traded':<23} | {'Gross P&L':>12} | {'Charges':>9} | {'Day Net P&L':>12} | {'Ending Wallet (₹)':>17}"
    )
    print("-" * 136)
    for row in daily_summary:
        wl = f"{row['wins']}/{row['losses']}"
        print(
            f"{row['date']:<10} | {row['close']:>11,.2f} | {row['trades']:>6d} | {wl:>7} | {row['lots']:>4d} | "
            f"{row['top_opt']:<23} | ₹{row['gross']:>+11,.2f} | ₹{row['charges']:>8,.2f} | "
            f"₹{row['net']:>+11,.2f} | ₹{row['wallet']:>16,.2f}"
        )
    print("-" * 136)

    # Executive Summary & Breakdown by Strike Type
    total_trades = len(all_trades)
    total_wins = sum(1 for t in all_trades if float(t["Net_PnL"]) > 0)
    total_losses = total_trades - total_wins
    win_rate = (total_wins / total_trades * 100.0) if total_trades else 0.0
    total_gross = sum(float(t["Gross_PnL"]) for t in all_trades)
    total_charges = sum(float(t["Charges"]) for t in all_trades)
    total_net = sum(float(t["Net_PnL"]) for t in all_trades)
    monthly_ret_pct = ((wallet - STARTING_WALLET) / STARTING_WALLET) * 100.0

    strike_buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "lots": 0, "gross": 0.0, "charges": 0.0, "net": 0.0}
    )
    for t in all_trades:
        st = t["Strike_Type"]
        b = strike_buckets[st]
        net_v = float(t["Net_PnL"])
        b["trades"] += 1
        b["wins"] += 1 if net_v > 0 else 0
        b["lots"] += int(t["Lots"])
        b["gross"] += float(t["Gross_PnL"])
        b["charges"] += float(t["Charges"])
        b["net"] += net_v

    print("\n" + "=" * 96)
    print("  OCTOBER 2026 UNRESTRICTED EXECUTIVE SUMMARY")
    print("=" * 96)
    print(f"Total Trading Days     : {len(daily_summary)}")
    print(f"Total Trades Executed  : {total_trades} (Wins: {total_wins} | Losses: {total_losses} | Win Rate: {win_rate:.2f}%)")
    print(f"Total Gross Profit     : ₹{total_gross:+,.2f}")
    print(f"Total Brokerage & Tax  : ₹{total_charges:,.2f}")
    print(f"Total Net Profit       : ₹{total_net:+,.2f}")
    print(f"Starting Wallet        : ₹{STARTING_WALLET:,.2f}")
    print(f"Final Ending Wallet    : ₹{wallet:,.2f} (Monthly Return: {monthly_ret_pct:+.2f}%)")
    print(f"CSV Exported           : {OUTPUT_CSV}")

    print("\nBreakdown by Strike Type (ITM / ATM / OTM Calls & Puts):")
    print(f"  {'Strike Type':<10} | {'Trades':>6} | {'Wins':>5} | {'Win %':>6} | {'Lots':>5} | {'Gross P&L':>12} | {'Net P&L':>12}")
    print("  " + "-" * 74)
    for st in ["ITM CE", "ATM CE", "OTM CE", "ITM PE", "ATM PE", "OTM PE"]:
        b = strike_buckets[st]
        wr = (b["wins"] / b["trades"] * 100.0) if b["trades"] else 0.0
        print(
            f"  {st:<10} | {b['trades']:>6d} | {b['wins']:>5d} | {wr:>5.1f}% | {b['lots']:>5d} | "
            f"₹{b['gross']:>+11,.2f} | ₹{b['net']:>+11,.2f}"
        )
    print("=" * 96)


if __name__ == "__main__":
    run_replay()
