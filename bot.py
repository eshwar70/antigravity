"""NIFTY 50 Momentum & ORB Options Scalping Bot using Upstox SDK V3."""

from __future__ import annotations

import csv
import gzip
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz
import requests
import upstox_client
from dotenv import set_key
from upstox_client.rest import ApiException

import config

IST = pytz.timezone(config.TIMEZONE)

CSV_HEADERS = [
    "Date",
    "Mode",
    "Symbol",
    "Instrument_Key",
    "Entry_Time",
    "Exit_Time",
    "Qty",
    "Spot_Entry",
    "Spot_Exit",
    "Option_Buy",
    "Option_Sell",
    "Highest_LTP",
    "Points_Captured",
    "Gross_PnL",
    "Charges",
    "Net_PnL",
    "Cumulative_Day_Net_PnL",
    "Exit_Reason",
]


def now_ist() -> datetime:
    return datetime.now(IST)


def parse_hms(hms: str) -> dt_time:
    parts = [int(x) for x in hms.split(":")]
    return dt_time(parts[0], parts[1], parts[2])


MARKET_OPEN_TIME = parse_hms(config.MARKET_OPEN)
INITIAL_ORB_END_TIME = parse_hms(config.INITIAL_ORB_END)
PRIMARY_ORB_END_TIME = parse_hms(config.PRIMARY_ORB_END)
LAST_NEW_ENTRY_TIME = parse_hms(config.LAST_NEW_ENTRY_TIME)
HARD_SQUARE_OFF_TIME = parse_hms(config.HARD_SQUARE_OFF_TIME)


def _to_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        num = float(val)
        if np.isnan(num) or np.isinf(num):
            return None
        return num
    except (TypeError, ValueError):
        return None


def _to_int(val: Any, default: int = 0) -> int:
    f = _to_float(val)
    return int(round(f)) if f is not None else default


def round_tick(price: float) -> float:
    return round(round(price / 0.05) * 0.05, 2)


@dataclass
class Bar:
    bucket_start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def update(self, price: float, delta_vol: float = 0.0) -> None:
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price
        self.close = price
        if delta_vol > 0:
            self.volume += delta_vol

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3.0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)


@dataclass
class OptionContract:
    instrument_key: str
    trading_symbol: str
    strike_price: float
    option_type: str  # "CE" or "PE"
    expiry_date: date
    lot_size: int = config.DEFAULT_LOT_SIZE


class InstrumentSeries:
    """Thread-safe 1-min & 5-min OHLCV bar aggregator and indicator store."""

    def __init__(self, instrument_key: str, max_bars: int = 600) -> None:
        self.instrument_key = instrument_key
        self.bars_1m: deque[Bar] = deque(maxlen=max_bars)
        self.bars_5m: deque[Bar] = deque(maxlen=max_bars)
        self.current_1m: Optional[Bar] = None
        self.current_5m: Optional[Bar] = None

        self.last_ltp: Optional[float] = None
        self.last_oi: float = 0.0
        self.last_vtt: Optional[float] = None
        self.last_tick_time: Optional[datetime] = None

        # Intraday VWAP state
        self.hist_pv: float = 0.0
        self.hist_vol: float = 0.0
        self.live_pv: float = 0.0
        self.live_vol: float = 0.0
        self.ew_sum: float = 0.0
        self.ew_count: int = 0
        self._last_hist_bar_end: Optional[datetime] = None

    @staticmethod
    def _bucket_1m(ts: datetime) -> datetime:
        return ts.replace(second=0, microsecond=0)

    @staticmethod
    def _bucket_5m(ts: datetime) -> datetime:
        return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)

    def seed_historical_1m(self, candles: List[Tuple[datetime, float, float, float, float, float]]) -> None:
        """Seed today's 1-minute historical bars (sorted oldest -> newest)."""
        if not candles:
            return
        cur_now = now_ist()
        cur_1m_bucket = self._bucket_1m(cur_now)

        for ts, o, h, l, c, vol in candles:
            if ts.date() != cur_now.date() or ts.time() < MARKET_OPEN_TIME:
                continue
            b1 = self._bucket_1m(ts)
            b5 = self._bucket_5m(ts)
            bar1 = Bar(bucket_start=b1, open=o, high=h, low=l, close=c, volume=max(0.0, vol))

            if b1 < cur_1m_bucket:
                if self.current_1m is None or b1 > self.current_1m.bucket_start:
                    if self.current_1m is not None:
                        self.bars_1m.append(self.current_1m)
                    self.current_1m = bar1
                if bar1.volume > 0:
                    self.hist_pv += bar1.typical_price * bar1.volume
                    self.hist_vol += bar1.volume
                else:
                    self.ew_sum += bar1.typical_price
                    self.ew_count += 1
                self._last_hist_bar_end = b1
            else:
                # Current in-progress minute
                if self.current_1m is not None and self.current_1m.bucket_start < b1:
                    self.bars_1m.append(self.current_1m)
                    self.current_1m = None
                if self.current_1m is None:
                    self.current_1m = bar1
                if bar1.volume > 0:
                    self.hist_pv += bar1.typical_price * bar1.volume
                    self.hist_vol += bar1.volume

            # Update 5-min bars from historical 1-min bars
            if self.current_5m is None:
                self.current_5m = Bar(bucket_start=b5, open=o, high=h, low=l, close=c, volume=max(0.0, vol))
            elif b5 > self.current_5m.bucket_start:
                self.bars_5m.append(self.current_5m)
                self.current_5m = Bar(bucket_start=b5, open=o, high=h, low=l, close=c, volume=max(0.0, vol))
            elif b5 == self.current_5m.bucket_start:
                self.current_5m.high = max(self.current_5m.high, h)
                self.current_5m.low = min(self.current_5m.low, l)
                self.current_5m.close = c
                self.current_5m.volume += max(0.0, vol)

            self.last_ltp = c
            self.last_tick_time = ts

        # Close out any completed 1-min bar if cur_1m_bucket has already moved past it
        if self.current_1m is not None and self.current_1m.bucket_start < cur_1m_bucket:
            self.bars_1m.append(self.current_1m)
            self.current_1m = None
        if self.current_5m is not None and self.current_5m.bucket_start < self._bucket_5m(cur_now):
            self.bars_5m.append(self.current_5m)
            self.current_5m = None

    def on_tick(
        self,
        price: float,
        ts: datetime,
        vtt: Optional[float] = None,
        oi: Optional[float] = None,
        ltq: Optional[float] = None,
    ) -> None:
        self.last_ltp = price
        self.last_tick_time = ts
        if oi is not None:
            self.last_oi = oi

        delta_vol = 0.0
        if vtt is not None and vtt >= 0:
            if self.last_vtt is None:
                self.last_vtt = vtt
                if ltq is not None and ltq > 0:
                    delta_vol = ltq
            else:
                if vtt >= self.last_vtt:
                    delta_vol = vtt - self.last_vtt
                self.last_vtt = vtt
        elif ltq is not None and ltq > 0:
            delta_vol = ltq

        # Do not accumulate intraday session bars/VWAP before 09:15 AM
        if ts.time() < MARKET_OPEN_TIME:
            return

        if delta_vol > 0:
            self.live_pv += price * delta_vol
            self.live_vol += delta_vol
        self.ew_sum += price
        self.ew_count += 1

        b1 = self._bucket_1m(ts)
        if self.current_1m is None:
            self.current_1m = Bar(bucket_start=b1, open=price, high=price, low=price, close=price, volume=delta_vol)
        elif b1 > self.current_1m.bucket_start:
            self.bars_1m.append(self.current_1m)
            self.current_1m = Bar(bucket_start=b1, open=price, high=price, low=price, close=price, volume=delta_vol)
        else:
            self.current_1m.update(price, delta_vol)

        b5 = self._bucket_5m(ts)
        if self.current_5m is None:
            self.current_5m = Bar(bucket_start=b5, open=price, high=price, low=price, close=price, volume=delta_vol)
        elif b5 > self.current_5m.bucket_start:
            self.bars_5m.append(self.current_5m)
            self.current_5m = Bar(bucket_start=b5, open=price, high=price, low=price, close=price, volume=delta_vol)
        else:
            self.current_5m.update(price, delta_vol)

    def get_vwap(self) -> Optional[float]:
        total_vol = self.hist_vol + self.live_vol
        if total_vol > 0:
            return (self.hist_pv + self.live_pv) / total_vol
        if self.ew_count > 0:
            return self.ew_sum / self.ew_count
        return self.last_ltp

    def get_1m_completed_closes(self) -> np.ndarray:
        return np.asarray([b.close for b in self.bars_1m], dtype=float)

    def get_1m_closes(self) -> np.ndarray:
        closes = [b.close for b in self.bars_1m]
        if self.current_1m is not None:
            closes.append(self.current_1m.close)
        return np.asarray(closes, dtype=float)

    def get_indicators(self) -> Dict[str, Optional[float]]:
        closes = self.get_1m_closes()[-120:]
        completed_closes = self.get_1m_completed_closes()[-120:]
        vwap = self.get_vwap()

        ema9_series = compute_ema_series(closes, 9) if len(closes) >= 5 else None
        ema9 = float(ema9_series[-1]) if ema9_series is not None else None
        ema9_prev = float(ema9_series[-2]) if (ema9_series is not None and len(ema9_series) >= 2) else ema9
        ema9_slope = (ema9 - ema9_prev) if (ema9 is not None and ema9_prev is not None) else None
        ema21 = compute_ema(closes, 21) if len(closes) >= 5 else None

        rsi5 = compute_wilder_rsi(closes, 5) if len(closes) >= 4 else None
        prev_rsi5 = compute_wilder_rsi(completed_closes, 5) if len(completed_closes) >= 4 else None
        rsi14 = compute_wilder_rsi(closes, 14) if len(closes) >= 4 else None

        sma20, upper_bb, lower_bb, bb_width = compute_bollinger_bands(closes, period=20, num_std=2.0)
        er10 = compute_kaufman_er(closes, period=10)

        return {
            "vwap": vwap,
            "ema9": ema9,
            "ema9_prev": ema9_prev,
            "ema9_slope": ema9_slope,
            "ema21": ema21,
            "rsi5": rsi5,
            "prev_rsi5": prev_rsi5,
            "rsi14": rsi14,
            "sma20": sma20,
            "upper_bb": upper_bb,
            "lower_bb": lower_bb,
            "bb_width": bb_width,
            "er10": er10,
            "bars_1m_count": float(len(closes)),
        }


def compute_ema_series(closes: np.ndarray, span: int) -> Optional[np.ndarray]:
    if len(closes) == 0:
        return None
    alpha = 2.0 / (span + 1.0)
    out = np.empty(len(closes), dtype=float)
    out[0] = float(closes[0])
    for i in range(1, len(closes)):
        out[i] = alpha * float(closes[i]) + (1.0 - alpha) * out[i - 1]
    return out


def compute_ema(closes: np.ndarray, span: int) -> Optional[float]:
    series = compute_ema_series(closes, span)
    return float(series[-1]) if series is not None else None


def compute_wilder_rsi(closes: np.ndarray, period: int = 14) -> Optional[float]:
    if len(closes) < 3:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    if len(deltas) >= period:
        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
            avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period
    else:
        avg_gain = float(np.mean(gains))
        avg_loss = float(np.mean(losses))

    if avg_loss <= 1e-12:
        return 100.0 if avg_gain > 1e-12 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_bollinger_bands(
    closes: np.ndarray, period: int = 20, num_std: float = 2.0
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if len(closes) < period:
        return None, None, None, None
    window = closes[-period:]
    sma = float(np.mean(window))
    std = float(np.std(window, ddof=0))
    upper = sma + num_std * std
    lower = sma - num_std * std
    width = ((upper - lower) / sma) if sma > 1e-9 else 0.0
    return sma, upper, lower, width


def compute_kaufman_er(closes: np.ndarray, period: int = 10) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    window = closes[-(period + 1) :]
    net_change = abs(float(window[-1]) - float(window[0]))
    volatility = float(np.sum(np.abs(np.diff(window))))
    if volatility <= 1e-9:
        return 0.0
    return min(1.0, max(0.0, net_change / volatility))


class ORBTracker:
    """Tracks 5-min (09:15-09:20) and 15-min (09:15-09:30) NIFTY Spot Opening Range."""

    def __init__(self) -> None:
        self.orb_5m_high: Optional[float] = None
        self.orb_5m_low: Optional[float] = None
        self.orb_15m_high: Optional[float] = None
        self.orb_15m_low: Optional[float] = None
        self.orb_high: Optional[float] = None
        self.orb_low: Optional[float] = None
        self.orb_ready: bool = False
        self.primary_15m_locked: bool = False

    def seed_from_spot_series(self, spot_series: InstrumentSeries, current_time: dt_time) -> None:
        bars = list(spot_series.bars_1m)
        if spot_series.current_1m is not None:
            bars.append(spot_series.current_1m)

        for b in bars:
            t = b.bucket_start.time()
            if t < MARKET_OPEN_TIME:
                continue
            if t < INITIAL_ORB_END_TIME:
                self.orb_5m_high = b.high if self.orb_5m_high is None else max(self.orb_5m_high, b.high)
                self.orb_5m_low = b.low if self.orb_5m_low is None else min(self.orb_5m_low, b.low)
            if t < PRIMARY_ORB_END_TIME:
                self.orb_15m_high = b.high if self.orb_15m_high is None else max(self.orb_15m_high, b.high)
                self.orb_15m_low = b.low if self.orb_15m_low is None else min(self.orb_15m_low, b.low)

        self.refresh_state(current_time)

    def on_spot_tick(self, price: float, ts: datetime) -> Optional[str]:
        t = ts.time()
        if t < MARKET_OPEN_TIME:
            return None
        if t < INITIAL_ORB_END_TIME:
            self.orb_5m_high = price if self.orb_5m_high is None else max(self.orb_5m_high, price)
            self.orb_5m_low = price if self.orb_5m_low is None else min(self.orb_5m_low, price)
        if t < PRIMARY_ORB_END_TIME:
            self.orb_15m_high = price if self.orb_15m_high is None else max(self.orb_15m_high, price)
            self.orb_15m_low = price if self.orb_15m_low is None else min(self.orb_15m_low, price)
        return self.refresh_state(t)

    def refresh_state(self, current_time: dt_time) -> Optional[str]:
        event_msg: Optional[str] = None
        if current_time >= INITIAL_ORB_END_TIME and not self.orb_ready:
            if self.orb_5m_high is not None and self.orb_5m_low is not None:
                self.orb_high = self.orb_5m_high
                self.orb_low = self.orb_5m_low
                self.orb_ready = True
                event_msg = (
                    f"5-Min ORB Established (09:15-09:20): "
                    f"HIGH={self.orb_high:.2f} | LOW={self.orb_low:.2f}"
                )
        if current_time >= PRIMARY_ORB_END_TIME and not self.primary_15m_locked:
            if self.orb_15m_high is not None and self.orb_15m_low is not None:
                self.orb_high = self.orb_15m_high
                self.orb_low = self.orb_15m_low
                self.orb_ready = True
                self.primary_15m_locked = True
                event_msg = (
                    f"15-Min Primary ORB Locked (09:15-09:30): "
                    f"HIGH={self.orb_high:.2f} | LOW={self.orb_low:.2f}"
                )
        return event_msg

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orb_5m_high": self.orb_5m_high,
            "orb_5m_low": self.orb_5m_low,
            "orb_15m_high": self.orb_15m_high,
            "orb_15m_low": self.orb_15m_low,
            "orb_high": self.orb_high,
            "orb_low": self.orb_low,
            "orb_ready": self.orb_ready,
            "primary_15m_locked": self.primary_15m_locked,
        }

    def load_dict(self, data: Dict[str, Any]) -> None:
        if not data:
            return
        for attr in (
            "orb_5m_high",
            "orb_5m_low",
            "orb_15m_high",
            "orb_15m_low",
            "orb_high",
            "orb_low",
        ):
            val = _to_float(data.get(attr))
            if val is not None:
                setattr(self, attr, val)
        self.orb_ready = bool(data.get("orb_ready", self.orb_ready))
        self.primary_15m_locked = bool(data.get("primary_15m_locked", self.primary_15m_locked))


def evaluate_all_weather_entry(
    spot_series: InstrumentSeries,
    contracts: Dict[str, OptionContract],
    option_series_map: Dict[str, InstrumentSeries],
    wallet_capital: float,
    lots: int = 1,
    min_premium: float = 15.0,
) -> Optional[Tuple[OptionContract, float, str, Dict[str, Optional[float]]]]:
    """
    4-Regime Adaptive Strategy Engine:
      1. VOLATILITY_SQUEEZE_IGNITION (Tight 10-bar range < 0.18% + Opt > Upper_BB + RSI_5 >= 60)
      2. TREND_PULLBACK_DIP       (Spot_ER_10 >= 0.38)
      3. MEAN_REVERSION_BOUNCE    (Spot_ER_10 < 0.38)
      4. LIQUIDITY_SWEEP_REVERSAL (15-min range stop-hunt sweep 3-12 pts + snapback <= 2 mins)
    Anti-overextension guard: never enters when (Option_LTP - Option_EMA9) > 4.0 pts.
    """
    spot_ltp = spot_series.last_ltp
    if spot_ltp is None or spot_ltp <= 0 or len(spot_series.bars_1m) < 1:
        return None

    spot_ind = spot_series.get_indicators()
    spot_ema9 = spot_ind.get("ema9")
    spot_ema21 = spot_ind.get("ema21")
    spot_er10 = spot_ind.get("er10")
    spot_rsi5 = spot_ind.get("rsi5")
    spot_prev_rsi5 = spot_ind.get("prev_rsi5")
    spot_sma20 = spot_ind.get("sma20")
    spot_upper_bb = spot_ind.get("upper_bb")
    spot_lower_bb = spot_ind.get("lower_bb")
    spot_bb_width = spot_ind.get("bb_width")

    if None in (spot_ema9, spot_ema21, spot_er10, spot_rsi5):
        return None
    assert spot_ema9 is not None and spot_ema21 is not None
    assert spot_er10 is not None and spot_rsi5 is not None

    prev_spot_bar = spot_series.bars_1m[-1]
    cur_spot_bar = spot_series.current_1m
    spot_cur_low = cur_spot_bar.low if cur_spot_bar is not None else spot_ltp
    spot_cur_high = cur_spot_bar.high if cur_spot_bar is not None else spot_ltp
    spot_cur_open = cur_spot_bar.open if cur_spot_bar is not None else prev_spot_bar.close

    # Precompute Strategy 3 (Volatility Squeeze)
    is_squeeze = False
    hi10 = 0.0
    lo10 = 0.0
    if len(spot_series.bars_1m) >= 10:
        bars10 = list(spot_series.bars_1m)[-10:]
        hi10 = max(b.high for b in bars10)
        lo10 = min(b.low for b in bars10)
        if spot_ltp > 0 and (hi10 - lo10) < 0.0018 * spot_ltp:
            is_squeeze = True

    # Precompute Strategy 4 (15-min Liquidity Sweep & <=2-min Snapback Reclaim)
    low_sweep = False
    high_sweep = False
    if len(spot_series.bars_1m) >= 17:
        ref_bars = list(spot_series.bars_1m)[-17:-2]
        ref_high = max(b.high for b in ref_bars)
        ref_low = min(b.low for b in ref_bars)
        recent_bars = list(spot_series.bars_1m)[-2:] + ([cur_spot_bar] if cur_spot_bar else [])
        recent_low = min(b.low for b in recent_bars)
        recent_high = max(b.high for b in recent_bars)
        low_sweep = (
            (3.0 <= (ref_low - recent_low) <= 12.0)
            and (spot_ltp > ref_low + 2.5)
            and (spot_ltp > spot_cur_open)
            and (spot_ltp > spot_ema9)
            and (spot_ltp > prev_spot_bar.close)
        )
        high_sweep = (
            (3.0 <= (recent_high - ref_high) <= 12.0)
            and (spot_ltp < ref_high - 2.5)
            and (spot_ltp < spot_cur_open)
            and (spot_ltp < spot_ema9)
            and (spot_ltp < prev_spot_bar.close)
        )

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
        if len(opt_series.bars_1m) < 1:
            continue

        opt_ind = opt_series.get_indicators()
        opt_ema9 = opt_ind.get("ema9")
        opt_ema9_slope = opt_ind.get("ema9_slope")
        opt_ema21 = opt_ind.get("ema21")
        opt_vwap = opt_ind.get("vwap")
        opt_rsi5 = opt_ind.get("rsi5")
        prev_opt_rsi5 = opt_ind.get("prev_rsi5")
        opt_upper_bb = opt_ind.get("upper_bb")

        if None in (opt_ema9, opt_ema21, opt_vwap, opt_rsi5):
            continue
        assert opt_ema9 is not None and opt_ema21 is not None
        assert opt_vwap is not None and opt_rsi5 is not None

        # Global Anti-Overextension Filter
        if (opt_ltp - opt_ema9) > config.OVEREXTENSION_MAX_PTS:
            continue

        prev_opt_bar = opt_series.bars_1m[-1]
        cur_opt_bar = opt_series.current_1m
        opt_cur_open = cur_opt_bar.open if cur_opt_bar is not None else prev_opt_bar.close
        opt_completed = opt_series.get_1m_completed_closes()[-120:]
        prev_opt_ema9 = compute_ema(opt_completed, 9) if len(opt_completed) >= 5 else opt_ema9
        if prev_opt_ema9 is None:
            prev_opt_ema9 = opt_ema9
        _, prev_opt_upper_bb, _, _ = compute_bollinger_bands(opt_completed, period=20, num_std=2.0)

        matched_strategy: Optional[str] = None

        # STRATEGY 3: VOLATILITY_SQUEEZE_IGNITION (Checked prior to mean-reversion so breakouts aren't faded)
        if is_squeeze and prev_opt_rsi5 is not None:
            ref_ubb = prev_opt_upper_bb if prev_opt_upper_bb is not None else opt_upper_bb
            spot_broke = (
                (contract.option_type == "CE" and spot_ltp > hi10 + 0.5 and spot_ltp > spot_ema9)
                or (contract.option_type == "PE" and spot_ltp < lo10 - 0.5 and spot_ltp < spot_ema9)
            )
            bb_compressed = spot_bb_width is None or spot_bb_width <= 0.0035
            if (
                ref_ubb is not None
                and bb_compressed
                and spot_broke
                and opt_ltp > ref_ubb
                and prev_opt_rsi5 < 60.0
                and opt_rsi5 >= 60.0
                and (opt_ltp - opt_ema9) <= 3.0
                and opt_ltp > opt_cur_open
                and (opt_ema9_slope is None or opt_ema9_slope > 0.0)
            ):
                matched_strategy = "VOLATILITY_SQUEEZE_IGNITION"

        # STRATEGY 1: TREND_PULLBACK_DIP (ER_10 >= 0.38)
        if (
            matched_strategy is None
            and spot_er10 >= config.ER_TREND_THRESHOLD
            and prev_opt_rsi5 is not None
        ):
            trend_aligned = (
                (contract.option_type == "CE" and spot_ema9 > spot_ema21 and opt_ema9 > opt_ema21)
                or (contract.option_type == "PE" and spot_ema9 < spot_ema21 and opt_ema9 > opt_ema21)
            )
            if trend_aligned:
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
                    matched_strategy = "TREND_PULLBACK_DIP"

        # STRATEGY 2: MEAN_REVERSION_BOUNCE (ER_10 < 0.38)
        if (
            matched_strategy is None
            and not is_squeeze
            and spot_er10 < config.ER_TREND_THRESHOLD
            and spot_lower_bb is not None
            and spot_upper_bb is not None
            and spot_sma20 is not None
            and spot_bb_width is not None
            and spot_bb_width >= 0.0020
        ):
            if contract.option_type == "CE":
                bottom_touched = (
                    spot_cur_low <= spot_lower_bb
                    or prev_spot_bar.low <= spot_lower_bb
                    or spot_rsi5 < 26.0
                    or (spot_prev_rsi5 is not None and spot_prev_rsi5 < 26.0)
                )
                reclaim_ok = (spot_ltp > spot_lower_bb) and ((spot_sma20 - spot_ltp) >= 12.0)
                bull_bounce = (
                    (spot_ltp > prev_spot_bar.high and spot_ltp > spot_cur_open)
                    or (opt_ltp > prev_opt_bar.close + 0.8 and opt_ltp > opt_cur_open + 0.3)
                )
                not_crashing = (spot_ema9 - spot_ema21) >= -15.0 or (spot_ltp > prev_spot_bar.high)
                if bottom_touched and reclaim_ok and bull_bounce and not_crashing and opt_ltp >= opt_ema9 - 0.5:
                    matched_strategy = "MEAN_REVERSION_BOUNCE"
            else:
                top_touched = (
                    spot_cur_high >= spot_upper_bb
                    or prev_spot_bar.high >= spot_upper_bb
                    or spot_rsi5 > 74.0
                    or (spot_prev_rsi5 is not None and spot_prev_rsi5 > 74.0)
                )
                reclaim_ok = (spot_ltp < spot_upper_bb) and ((spot_ltp - spot_sma20) >= 12.0)
                bear_reject = (
                    (spot_ltp < prev_spot_bar.low and spot_ltp < spot_cur_open)
                    or (opt_ltp > prev_opt_bar.close + 0.8 and opt_ltp > opt_cur_open + 0.3)
                )
                not_ripping = (spot_ema9 - spot_ema21) <= 15.0 or (spot_ltp < prev_spot_bar.low)
                if top_touched and reclaim_ok and bear_reject and not_ripping and opt_ltp >= opt_ema9 - 0.5:
                    matched_strategy = "MEAN_REVERSION_BOUNCE"

        # STRATEGY 4: LIQUIDITY_SWEEP_REVERSAL
        if matched_strategy is None:
            if (
                (
                    (contract.option_type == "CE" and low_sweep)
                    or (contract.option_type == "PE" and high_sweep)
                )
                and opt_ltp > prev_opt_bar.close + 0.8
                and opt_ltp > opt_cur_open + 0.3
                and opt_ltp >= opt_ema9
                and opt_ltp > opt_vwap
                and (opt_ema9_slope is None or opt_ema9_slope > 0.0)
                and 50.0 <= opt_rsi5 <= 76.0
            ):
                matched_strategy = "LIQUIDITY_SWEEP_REVERSAL"

        if matched_strategy is not None:
            # Prefer ATM / slightly ITM sweet spot (~₹115, ~0.55 Delta) & clean entry near EMA9
            sweet_bonus = 10.0 if (config.MIN_OPTION_PREMIUM <= opt_ltp <= config.MAX_OPTION_PREMIUM) else 0.0
            vwap_bonus = 3.0 if opt_ltp > opt_vwap else 0.0
            ema_dist_pen = abs(opt_ltp - opt_ema9)
            prem_dist_pen = abs(opt_ltp - 115.0) * 0.05
            rank_score = sweet_bonus + vwap_bonus - ema_dist_pen - prem_dist_pen
            matches.append((rank_score, contract, opt_ltp, matched_strategy, opt_ind))

    if not matches:
        return None

    matches.sort(key=lambda x: x[0], reverse=True)
    _, best_c, best_ltp, best_strat, best_ind = matches[0]
    return best_c, best_ltp, best_strat, best_ind


def evaluate_micro_scalp_exit(
    entry_price: float,
    current_ltp: float,
    highest_ltp: float,
    sl_price: float,
    minutes_held: float,
    ts_time: dt_time,
    realized_day_net_pnl: float,
    qty: int,
    charges: float,
    max_daily_loss_inr: float,
) -> Tuple[float, float, Optional[str], Optional[float]]:
    """
    Tick-by-Tick Micro-Scalp Exit Ladder:
      1. Emergency/Daily Kill-Switch check
      2. Mandatory Hard Square-Off (15:28:00)
      3. Instant Sniper Target (+9.0 pts -> QUICK_TARGET_HIT)
      4. Step-Trail Ladder (+6.5 -> High-1.0 | +5.0 -> +4.0 | +3.2 -> +1.2)
      5. 5-Minute Fast Scratch (>=5m & peak < +3.2: exit >= +1.0 else SL = -2.5)
      6. Stop-Loss breach check
    Returns (new_highest_ltp, new_sl_price, exit_reason_or_none, target_exit_ltp_or_none).
    """
    new_high = max(highest_ltp, current_ltp)
    gain = current_ltp - entry_price
    peak_gain = new_high - entry_price
    new_sl = sl_price

    if peak_gain >= config.MICRO_TRAIL_TRIGGER_PTS:
        new_sl = max(new_sl, round(new_high - config.MICRO_TRAIL_GAP_PTS, 1))
    elif peak_gain >= config.QUICK_LOCK_TRIGGER_PTS:
        new_sl = max(new_sl, round(entry_price + config.QUICK_LOCK_SL_PTS, 1))
    elif peak_gain >= config.BREAKEVEN_TRIGGER_PTS:
        new_sl = max(new_sl, round(entry_price + config.BREAKEVEN_LOCK_PTS, 1))

    if minutes_held >= config.FAST_SCRATCH_MINS and peak_gain < config.BREAKEVEN_TRIGGER_PTS:
        if gain >= config.FAST_SCRATCH_PROFIT_PTS:
            return new_high, new_sl, "FAST_SCRATCH_PROFIT", current_ltp
        new_sl = max(new_sl, round(entry_price + config.FAST_SCRATCH_SL_OFFSET, 1))

    live_day_net = realized_day_net_pnl + (gain * qty) - charges
    if live_day_net <= max_daily_loss_inr:
        return new_high, new_sl, "DAILY_KILL_SWITCH", current_ltp

    if ts_time >= HARD_SQUARE_OFF_TIME:
        return new_high, new_sl, "HARD_SQUARE_OFF", current_ltp

    if gain >= config.INSTANT_TAKE_PROFIT_PTS:
        return new_high, new_sl, "QUICK_TARGET_HIT", round(entry_price + config.INSTANT_TAKE_PROFIT_PTS, 2)

    if current_ltp <= new_sl:
        if new_sl > entry_price:
            reason = "TRAILING_SL"
        elif minutes_held >= config.FAST_SCRATCH_MINS and new_sl >= round(entry_price + config.FAST_SCRATCH_SL_OFFSET, 1):
            reason = "FAST_SCRATCH_SL"
        else:
            reason = "STOP_LOSS"
        return new_high, new_sl, reason, current_ltp

    return new_high, new_sl, None, None


# =====================================================================
# AUTHENTICATION, INSTRUMENT MASTER & REST HELPERS
# =====================================================================

def make_api_client(access_token: str) -> upstox_client.ApiClient:
    cfg = upstox_client.Configuration(sandbox=False)
    cfg.access_token = access_token
    return upstox_client.ApiClient(cfg)


def validate_access_token(access_token: str) -> Tuple[bool, str]:
    if not access_token:
        return False, "No ACCESS_TOKEN found."
    try:
        client = make_api_client(access_token)
        user_api = upstox_client.UserApi(client)
        profile = user_api.get_profile("2.0")
        data = getattr(profile, "data", None)
        user_name = getattr(data, "user_name", None) or getattr(data, "email", None) or "Verified User"
        user_id = getattr(data, "user_id", "")
        label = f"{user_name} ({user_id})" if user_id else str(user_name)
        return True, label
    except ApiException as exc:
        return False, f"HTTP {exc.status}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


def save_env_var(key: str, value: str) -> None:
    if not os.path.exists(config.DOTENV_PATH):
        with open(config.DOTENV_PATH, "w", encoding="utf-8") as fh:
            fh.write("")
    set_key(config.DOTENV_PATH, key, value)
    os.environ[key] = value
    setattr(config, key, value)


def exchange_auth_code_for_token(code: str, api_key: str, api_secret: str, redirect_uri: str) -> str:
    url = "https://api.upstox.com/v2/login/authorization/token"
    headers = {
        "accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    payload = {
        "code": code,
        "client_id": api_key,
        "client_secret": api_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    resp = requests.post(url, headers=headers, data=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token", "").strip()
    if not token:
        raise ValueError(f"Token response missing access_token: {data}")
    return token


def run_step_a_login() -> str:
    print("\n" + "=" * 72)
    print("STEP A — UPSTOX MORNING LOGIN & TOKEN VERIFICATION")
    print("=" * 72)

    token = config.ACCESS_TOKEN
    if token:
        ok, info = validate_access_token(token)
        if ok:
            print(f"[AUTH OK] Existing ACCESS_TOKEN is valid -> {info}")
            return token
        print(f"[AUTH EXPIRED] Existing ACCESS_TOKEN rejected ({info}).")

    while True:
        if config.API_KEY:
            encoded_redirect = urllib.parse.quote(config.REDIRECT_URI, safe="")
            login_url = (
                "https://api.upstox.com/v2/login/authorization/dialog"
                f"?response_type=code&client_id={config.API_KEY}&redirect_uri={encoded_redirect}"
            )
            print("\nOpen this Upstox Login URL in your browser to authorize today's session:")
            print(f"  {login_url}\n")
        else:
            print("\n[INFO] API_KEY is not set in .env; paste a valid ACCESS_TOKEN directly or configure API_KEY.")

        raw = input(
            "Paste today's Upstox ACCESS_TOKEN (or paste the redirected URL / auth 'code' to auto-generate token): "
        ).strip()
        if not raw:
            print("[WARN] Input cannot be empty.")
            continue

        candidate_token = ""
        extracted_code = ""
        if raw.lower().startswith("http") or "code=" in raw:
            parsed = urllib.parse.urlparse(raw)
            qs = urllib.parse.parse_qs(parsed.query)
            extracted_code = (qs.get("code") or [""])[0].strip()
            if not extracted_code:
                print("[ERROR] Could not find 'code=' query parameter in the pasted URL.")
                continue
        elif "." not in raw and len(raw) < 60:
            extracted_code = raw
        else:
            candidate_token = raw

        if extracted_code:
            api_key = config.API_KEY or input("Enter Upstox API_KEY: ").strip()
            api_secret = config.API_SECRET or input("Enter Upstox API_SECRET: ").strip()
            if not api_key or not api_secret:
                print("[ERROR] API_KEY and API_SECRET are required to exchange auth code.")
                continue
            if not config.API_KEY:
                save_env_var("API_KEY", api_key)
            if not config.API_SECRET:
                save_env_var("API_SECRET", api_secret)
            try:
                candidate_token = exchange_auth_code_for_token(
                    extracted_code, api_key, api_secret, config.REDIRECT_URI
                )
            except Exception as exc:
                print(f"[ERROR] Failed to exchange auth code for token: {exc}")
                continue

        ok, info = validate_access_token(candidate_token)
        if ok:
            save_env_var("ACCESS_TOKEN", candidate_token)
            print(f"[AUTH OK] Token verified and saved to .env -> {info}")
            return candidate_token
        print(f"[ERROR] Token verification failed ({info}). Please try again.")


def run_step_b_mode() -> str:
    print("\n" + "=" * 72)
    print("STEP B — EXECUTION MODE SELECTION")
    print("=" * 72)
    while True:
        choice = input(
            "Select Execution Mode -> [P] Practice Mode (Live Market Prices, Fake Money) "
            "| [L] Live Mode (Real Upstox Orders) [Default: P]: "
        ).strip().upper()
        if choice == "" or choice == "P":
            print("[MODE] Practice Mode [P] selected — 100% live WebSocket ticks, simulated fills.")
            return "P"
        if choice == "L":
            print(
                f"[MODE] LIVE Mode [L] selected — Real Upstox V3 Orders | "
                f"Daily Kill-Switch: ₹{config.MAX_DAILY_LOSS_INR:,.2f}"
            )
            return "L"
        print("[WARN] Please enter 'P' or 'L'.")


def _parse_expiry_date(raw_expiry: Any) -> Optional[date]:
    if raw_expiry is None or raw_expiry == "":
        return None
    if isinstance(raw_expiry, (int, float)) or (isinstance(raw_expiry, str) and raw_expiry.strip().isdigit()):
        val = float(raw_expiry)
        if val > 1e11:
            return datetime.fromtimestamp(val / 1000.0, tz=IST).date()
        if val > 1e8:
            return datetime.fromtimestamp(val, tz=IST).date()
        return None
    if isinstance(raw_expiry, str):
        s = raw_expiry.strip()[:10]
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def load_nifty_weekly_options() -> Tuple[date, List[OptionContract]]:
    cache_path = os.path.join(config.BASE_DIR, config.INSTRUMENT_CACHE)
    today = now_ist().date()

    need_download = True
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        mtime_ist = datetime.fromtimestamp(os.path.getmtime(cache_path), tz=IST).date()
        if mtime_ist == today:
            need_download = False

    if need_download:
        print(f"[DATA] Downloading daily NSE Instrument Master -> {config.INSTRUMENT_CACHE} ...")
        try:
            resp = requests.get(config.INSTRUMENT_MASTER_URL, timeout=60)
            resp.raise_for_status()
            tmp_path = cache_path + ".tmp"
            with open(tmp_path, "wb") as fh:
                fh.write(resp.content)
            os.replace(tmp_path, cache_path)
            print("[DATA] Instrument Master cached for today.")
        except Exception as exc:
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
                print(f"[WARN] Download failed ({exc}); using cached {config.INSTRUMENT_CACHE}.")
            else:
                raise RuntimeError(f"Failed to download NSE instrument master: {exc}") from exc
    else:
        print(f"[DATA] Using today's cached {config.INSTRUMENT_CACHE}.")

    with gzip.open(cache_path, "rt", encoding="utf-8") as gz:
        records = json.load(gz)

    nifty_records: List[Tuple[date, dict]] = []
    upcoming_expiries = set()

    for rec in records:
        if (
            rec.get("segment") == "NSE_FO"
            and rec.get("name") == "NIFTY"
            and rec.get("instrument_type") in ("CE", "PE")
        ):
            exp_date = _parse_expiry_date(rec.get("expiry"))
            if exp_date is not None and exp_date >= today:
                upcoming_expiries.add(exp_date)
                nifty_records.append((exp_date, rec))

    if not upcoming_expiries:
        raise RuntimeError("No upcoming NIFTY option expiries found in NSE instrument master.")

    nearest_expiry = min(upcoming_expiries)
    contracts: List[OptionContract] = []
    for exp_date, rec in nifty_records:
        if exp_date != nearest_expiry:
            continue
        strike = _to_float(rec.get("strike_price"))
        inst_key = str(rec.get("instrument_key") or "").strip()
        sym = str(rec.get("trading_symbol") or rec.get("tradingsymbol") or inst_key).strip()
        opt_type = str(rec.get("instrument_type")).strip().upper()
        lot_size = _to_int(rec.get("lot_size"), config.DEFAULT_LOT_SIZE)
        if lot_size <= 0:
            lot_size = config.DEFAULT_LOT_SIZE
        if strike is None or not inst_key:
            continue
        contracts.append(
            OptionContract(
                instrument_key=inst_key,
                trading_symbol=sym,
                strike_price=round(strike, 2),
                option_type=opt_type,
                expiry_date=nearest_expiry,
                lot_size=lot_size,
            )
        )

    contracts.sort(key=lambda c: (c.strike_price, c.option_type))
    return nearest_expiry, contracts


def _lookup_quote_entry(data_map: Dict[str, Any], inst_key: str) -> Optional[Dict[str, Any]]:
    if inst_key in data_map:
        return data_map[inst_key]
    colon_key = inst_key.replace("|", ":")
    if colon_key in data_map:
        return data_map[colon_key]
    for entry in data_map.values():
        if isinstance(entry, dict) and entry.get("instrument_token") == inst_key:
            return entry
    return None


def fetch_spot_ltp(access_token: str) -> float:
    url = "https://api.upstox.com/v2/market-quote/ltp"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers, params={"instrument_key": config.SPOT_KEY}, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    data_map = payload.get("data") or {}
    entry = _lookup_quote_entry(data_map, config.SPOT_KEY)
    if entry is None and data_map:
        entry = next(iter(data_map.values()))
    ltp = _to_float((entry or {}).get("last_price"))
    if ltp is None or ltp <= 0:
        raise RuntimeError(f"Invalid Nifty 50 Spot LTP response: {payload}")
    return ltp


def fetch_full_quotes(access_token: str, instrument_keys: List[str]) -> Dict[str, Dict[str, Any]]:
    if not instrument_keys:
        return {}
    url = "https://api.upstox.com/v2/market-quote/quotes"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    results: Dict[str, Dict[str, Any]] = {}
    # Batch in chunks of 50 to stay well within Upstox URL/key limits
    for i in range(0, len(instrument_keys), 50):
        batch = instrument_keys[i : i + 50]
        resp = requests.get(
            url,
            headers=headers,
            params={"instrument_key": ",".join(batch)},
            timeout=20,
        )
        resp.raise_for_status()
        data_map = resp.json().get("data") or {}
        for key in batch:
            entry = _lookup_quote_entry(data_map, key)
            if entry:
                results[key] = entry
    return results


def fetch_intraday_1m_candles(
    access_token: str, instrument_key: str
) -> List[Tuple[datetime, float, float, float, float, float]]:
    encoded = urllib.parse.quote(instrument_key, safe="")
    url = f"https://api.upstox.com/v2/historical-candle/intraday/{encoded}/1minute"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        return []
    candles_raw = (resp.json().get("data") or {}).get("candles") or []
    parsed: List[Tuple[datetime, float, float, float, float, float]] = []
    for row in candles_raw:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            dt = datetime.fromisoformat(str(row[0]))
            if dt.tzinfo is None:
                dt = IST.localize(dt)
            else:
                dt = dt.astimezone(IST)
            o = _to_float(row[1])
            h = _to_float(row[2])
            l = _to_float(row[3])
            c = _to_float(row[4])
            vol = _to_float(row[5]) or 0.0
            if None in (o, h, l, c):
                continue
            parsed.append((dt, float(o), float(h), float(l), float(c), float(vol)))
        except Exception:
            continue
    parsed.sort(key=lambda item: item[0])
    return parsed


def _score_option_candidate(contract: OptionContract, quote: Dict[str, Any]) -> Tuple[bool, float, float]:
    ltp = _to_float(quote.get("last_price")) or 0.0
    if ltp <= 0:
        return False, -1e9, 0.0
    cost = ltp * contract.lot_size * config.LOTS_PER_TRADE
    vol = _to_float(quote.get("volume")) or 0.0
    oi = _to_float(quote.get("oi")) or 0.0
    ohlc = quote.get("ohlc") or {}
    open_px = _to_float(ohlc.get("open")) or ltp
    momentum_pct = abs(ltp - open_px) / open_px if open_px > 0 else 0.0

    in_sweet_spot = config.MIN_OPTION_PREMIUM <= ltp <= config.MAX_OPTION_PREMIUM
    affordable = cost <= config.WALLET_CAPITAL

    liquidity_score = np.log1p(vol) * 1.5 + np.log1p(oi) * 1.2
    sweet_bonus = 25.0 if in_sweet_spot else -abs(ltp - 112.5) * 0.25
    wallet_bonus = 20.0 if affordable else -100.0
    momentum_bonus = momentum_pct * 30.0
    total_score = float(liquidity_score + sweet_bonus + wallet_bonus + momentum_bonus)
    return (in_sweet_spot and affordable), total_score, ltp


def run_step_c_strikes(
    access_token: str,
    spot_ltp: float,
    expiry_date: date,
    contracts: List[OptionContract],
) -> List[OptionContract]:
    print("\n" + "=" * 72)
    print("STEP C — DAILY STRIKE SELECTION")
    print("=" * 72)
    print(f"Nifty 50 Spot LTP : {spot_ltp:.2f} | Nearest Weekly Expiry : {expiry_date.strftime('%d-%b-%Y')}")

    by_strike_type: Dict[Tuple[float, str], OptionContract] = {
        (c.strike_price, c.option_type): c for c in contracts
    }

    print(
        '\n[1] Auto-Pick High-Probability Profit Strikes '
        '(Scans ATM/Near-OTM strikes in ₹70–₹155 sweet spot with highest momentum/OI)'
    )
    print(
        "[2] Enter Your Preferred Strike(s) for Today "
        "(e.g., '25050' for both CE & PE, or comma-separated '25050CE, 25100CE, 24950PE')"
    )

    while True:
        choice = input("\nChoose option [1] or [2] [Default: 1]: ").strip() or "1"

        if choice == "1":
            atm = round(spot_ltp / 50.0) * 50.0
            scan_strikes = [atm + offset for offset in (-100.0, -50.0, 0.0, 50.0, 100.0)]
            candidates: List[OptionContract] = []
            for s in scan_strikes:
                for opt_type in ("CE", "PE"):
                    c = by_strike_type.get((s, opt_type))
                    if c:
                        candidates.append(c)

            quotes = fetch_full_quotes(access_token, [c.instrument_key for c in candidates])

            def pick_best(opt_type: str, pool: List[OptionContract], qmap: Dict[str, Dict[str, Any]]) -> Optional[OptionContract]:
                scored: List[Tuple[bool, float, OptionContract, float, float, float]] = []
                for c in pool:
                    if c.option_type != opt_type:
                        continue
                    q = qmap.get(c.instrument_key) or {}
                    ideal, score, ltp = _score_option_candidate(c, q)
                    if ltp > 0:
                        vol = _to_float(q.get("volume")) or 0.0
                        oi = _to_float(q.get("oi")) or 0.0
                        scored.append((ideal, score, c, ltp, vol, oi))
                if not scored:
                    return None
                scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
                return scored[0][2]

            best_ce = pick_best("CE", candidates, quotes)
            best_pe = pick_best("PE", candidates, quotes)

            # Fallback scan +/- 250 around ATM if the +/- 100 band had no sweet-spot strike
            ce_ltp = _to_float((quotes.get(best_ce.instrument_key) or {}).get("last_price")) if best_ce else 0.0
            pe_ltp = _to_float((quotes.get(best_pe.instrument_key) or {}).get("last_price")) if best_pe else 0.0
            ce_in_band = best_ce is not None and config.MIN_OPTION_PREMIUM <= (ce_ltp or 0.0) <= config.MAX_OPTION_PREMIUM
            pe_in_band = best_pe is not None and config.MIN_OPTION_PREMIUM <= (pe_ltp or 0.0) <= config.MAX_OPTION_PREMIUM

            if not (ce_in_band and pe_in_band):
                wider_strikes = [atm + offset for offset in range(-250, 300, 50) if (atm + offset) not in scan_strikes]
                wider_pool = [
                    by_strike_type[(float(s), t)]
                    for s in wider_strikes
                    for t in ("CE", "PE")
                    if (float(s), t) in by_strike_type
                ]
                if wider_pool:
                    wider_quotes = fetch_full_quotes(access_token, [c.instrument_key for c in wider_pool])
                    merged_pool = candidates + wider_pool
                    merged_quotes = {**quotes, **wider_quotes}
                    if not ce_in_band:
                        alt_ce = pick_best("CE", merged_pool, merged_quotes)
                        if alt_ce:
                            best_ce = alt_ce
                    if not pe_in_band:
                        alt_pe = pick_best("PE", merged_pool, merged_quotes)
                        if alt_pe:
                            best_pe = alt_pe
                    quotes = merged_quotes

            selected: List[OptionContract] = [c for c in (best_ce, best_pe) if c is not None]
            if not selected:
                print("[ERROR] Could not resolve active option quotes. Try manual strike entry [2].")
                continue

            print("\nSelected Auto-Pick Strikes:")
            for c in selected:
                q = quotes.get(c.instrument_key) or {}
                ltp = _to_float(q.get("last_price")) or 0.0
                vol = _to_int(q.get("volume"))
                oi = _to_int(q.get("oi"))
                cost = ltp * c.lot_size * config.LOTS_PER_TRADE
                print(
                    f"  - {c.trading_symbol} ({c.instrument_key}) | LTP: ₹{ltp:.2f} | "
                    f"1-Lot Cost: ₹{cost:,.2f} | Vol: {vol:,} | OI: {oi:,}"
                )
            return selected

        if choice == "2":
            raw_strikes = input(
                "Enter Strike(s) (e.g., '25050' or '25050CE, 25100CE, 24950PE'): "
            ).strip()
            if not raw_strikes:
                print("[WARN] Please enter at least one strike.")
                continue

            tokens = [tok.strip() for tok in raw_strikes.split(",") if tok.strip()]
            selected = []
            seen_keys = set()
            invalid_tokens: List[str] = []

            for tok in tokens:
                m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(CE|PE)?\s*$", tok, flags=re.IGNORECASE)
                if not m:
                    invalid_tokens.append(tok)
                    continue
                strike_val = round(float(m.group(1)), 2)
                opt_types = [m.group(2).upper()] if m.group(2) else ["CE", "PE"]
                for ot in opt_types:
                    c = by_strike_type.get((strike_val, ot))
                    if c is None:
                        invalid_tokens.append(f"{int(strike_val) if strike_val.is_integer() else strike_val}{ot}")
                    elif c.instrument_key not in seen_keys:
                        seen_keys.add(c.instrument_key)
                        selected.append(c)

            if invalid_tokens:
                print(f"[WARN] Unmatched strike token(s) for expiry {expiry_date}: {', '.join(invalid_tokens)}")
            if not selected:
                print("[ERROR] No valid strikes selected. Please try again.")
                continue

            quotes = fetch_full_quotes(access_token, [c.instrument_key for c in selected])
            print("\nSelected Manual Strikes:")
            for c in selected:
                q = quotes.get(c.instrument_key) or {}
                ltp = _to_float(q.get("last_price")) or 0.0
                cost = ltp * c.lot_size * config.LOTS_PER_TRADE
                warn = (
                    f" [ABOVE ₹{config.WALLET_CAPITAL:,.0f} WALLET]"
                    if cost > config.WALLET_CAPITAL
                    else ""
                )
                print(
                    f"  - {c.trading_symbol} ({c.instrument_key}) | LTP: ₹{ltp:.2f} | "
                    f"1-Lot Cost: ₹{cost:,.2f} (Lot={c.lot_size}){warn}"
                )
            return selected

        print("[WARN] Invalid choice. Please enter 1 or 2.")


# =====================================================================
# LIVE TRADING ENGINE
# =====================================================================

class NiftyScalperBot:
    def __init__(
        self,
        access_token: str,
        mode: str,
        watched_contracts: List[OptionContract],
        all_contracts_by_key: Dict[str, OptionContract],
    ) -> None:
        self.access_token = access_token
        self.api_client = make_api_client(access_token)
        self.order_api = upstox_client.OrderApiV3(self.api_client)
        self.mode = mode  # "P" or "L"
        self.all_contracts_by_key = all_contracts_by_key
        self.contracts_by_strike_type: Dict[Tuple[float, str], OptionContract] = {
            (round(c.strike_price, 2), c.option_type): c
            for c in all_contracts_by_key.values()
        }

        self.watched_contracts: Dict[str, OptionContract] = {
            c.instrument_key: c for c in watched_contracts
        }
        self.hedge_contracts: Dict[str, OptionContract] = {}
        self.spot_series = InstrumentSeries(config.SPOT_KEY)
        self.option_series: Dict[str, InstrumentSeries] = {
            c.instrument_key: InstrumentSeries(c.instrument_key) for c in watched_contracts
        }
        if config.ALLOW_HEDGING:
            for c in watched_contracts:
                wing_strike = (
                    c.strike_price + config.HEDGE_WING_OFFSET
                    if c.option_type == "CE"
                    else c.strike_price - config.HEDGE_WING_OFFSET
                )
                wing = self.contracts_by_strike_type.get((round(wing_strike, 2), c.option_type))
                if wing is not None:
                    self.hedge_contracts[wing.instrument_key] = wing
                    if wing.instrument_key not in self.option_series:
                        self.option_series[wing.instrument_key] = InstrumentSeries(wing.instrument_key)

        self.orb = ORBTracker()

        self.lock = threading.RLock()
        self.print_lock = threading.Lock()
        self.stop_event = threading.Event()

        self.open_position: Optional[Dict[str, Any]] = None
        self.realized_net_pnl: float = 0.0
        self.trade_count: int = 0
        self.kill_switch_triggered: bool = False
        self.last_exit_time: Optional[datetime] = None
        self.ws_connected: bool = False
        self.streamer: Any = None

        self.state_path = os.path.join(config.BASE_DIR, config.STATE_FILE)
        self.csv_path = os.path.join(config.BASE_DIR, config.TRADE_LOG_CSV)

        self._ensure_csv_header()
        self._load_state()
        self._backfill_intraday_history()

    def log_event(self, msg: str) -> None:
        ts = now_ist().strftime("%H:%M:%S")
        with self.print_lock:
            sys.stdout.write(f"\r\x1b[2K[{ts}] {msg}\n")
            sys.stdout.flush()

    def _ensure_csv_header(self) -> None:
        if not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0:
            with open(self.csv_path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(CSV_HEADERS)

    def _append_trade_csv(self, row: List[Any]) -> None:
        with open(self.csv_path, "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(row)
            fh.flush()

    def _save_state(self) -> None:
        today_str = now_ist().strftime("%Y-%m-%d")
        payload = {
            "date": today_str,
            "mode": self.mode,
            "realized_net_pnl": round(self.realized_net_pnl, 2),
            "trade_count": self.trade_count,
            "kill_switch_triggered": self.kill_switch_triggered,
            "last_exit_time": self.last_exit_time.isoformat() if self.last_exit_time else None,
            "orb": self.orb.to_dict(),
            "open_position": self.open_position,
        }
        tmp_path = self.state_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp_path, self.state_path)

    def _load_state(self) -> None:
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            self.log_event(f"[WARN] Could not parse state.json ({exc}); starting fresh state.")
            return

        today_str = now_ist().strftime("%Y-%m-%d")
        if data.get("date") != today_str:
            self.log_event(f"[STATE] Previous state.json is from {data.get('date')}; resetting for {today_str}.")
            return

        # Always recover today's Spot ORB range if present
        self.orb.load_dict(data.get("orb") or {})

        saved_mode = data.get("mode")
        if saved_mode == self.mode:
            self.realized_net_pnl = float(data.get("realized_net_pnl") or 0.0)
            self.trade_count = int(data.get("trade_count") or 0)
            self.kill_switch_triggered = bool(data.get("kill_switch_triggered", False))
            raw_exit = data.get("last_exit_time")
            if raw_exit:
                try:
                    dt = datetime.fromisoformat(raw_exit)
                    self.last_exit_time = dt if dt.tzinfo else IST.localize(dt)
                except ValueError:
                    self.last_exit_time = None

        pos = data.get("open_position")
        if isinstance(pos, dict) and pos.get("instrument_key"):
            inst_key = str(pos["instrument_key"])
            if inst_key not in self.watched_contracts:
                contract = self.all_contracts_by_key.get(inst_key)
                if contract is None:
                    contract = OptionContract(
                        instrument_key=inst_key,
                        trading_symbol=str(pos.get("trading_symbol") or inst_key),
                        strike_price=float(pos.get("strike") or 0.0),
                        option_type=str(pos.get("option_type") or "CE"),
                        expiry_date=now_ist().date(),
                        lot_size=int(pos.get("qty") or config.DEFAULT_LOT_SIZE),
                    )
                self.watched_contracts[inst_key] = contract
                self.option_series[inst_key] = InstrumentSeries(inst_key)
            self.open_position = pos
            short_key = str(pos.get("short_instrument_key") or "").strip()
            if short_key and short_key not in self.option_series:
                short_c = self.all_contracts_by_key.get(short_key) or OptionContract(
                    instrument_key=short_key,
                    trading_symbol=str(pos.get("short_trading_symbol") or short_key),
                    strike_price=float(pos.get("short_strike") or 0.0),
                    option_type=str(pos.get("option_type") or "CE"),
                    expiry_date=now_ist().date(),
                    lot_size=int(pos.get("lot_size") or config.DEFAULT_LOT_SIZE),
                )
                self.hedge_contracts[short_key] = short_c
                self.option_series[short_key] = InstrumentSeries(short_key)
            pos_mode = pos.get("mode", saved_mode or self.mode)
            self.log_event(
                f"[RECOVERED TRADE] Resuming {pos_mode} ({pos.get('strategy_mode', 'NAKED_DIRECTIONAL')}) "
                f"position: {pos.get('trading_symbol')} @ ₹{float(pos.get('entry_price', 0.0)):.2f} "
                f"| SL: ₹{float(pos.get('sl_price', 0.0)):.2f}"
            )

    def _backfill_intraday_history(self) -> None:
        self.log_event("[INIT] Backfilling today's 1-min intraday bars for ORB, VWAP, EMA & RSI...")
        spot_candles = fetch_intraday_1m_candles(self.access_token, config.SPOT_KEY)
        if spot_candles:
            self.spot_series.seed_historical_1m(spot_candles)
            self.orb.seed_from_spot_series(self.spot_series, now_ist().time())
            if self.orb.orb_ready:
                self.log_event(
                    f"[ORB READY] High={self.orb.orb_high:.2f} | Low={self.orb.orb_low:.2f} "
                    f"({'15m Locked' if self.orb.primary_15m_locked else '5m Initial'})"
                )
        for inst_key, series in self.option_series.items():
            candles = fetch_intraday_1m_candles(self.access_token, inst_key)
            if candles:
                series.seed_historical_1m(candles)

    # ------------------------------------------------------------------
    # ORDER EXECUTION (V3 HFT + DETAILS POLL + FALLBACK)
    # ------------------------------------------------------------------

    def _poll_order_details(self, order_id: str, timeout_secs: float = 1.5) -> Tuple[str, Optional[float]]:
        url = "https://api.upstox.com/v2/order/details"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.access_token}"}
        deadline = time.monotonic() + timeout_secs
        last_status = "unknown"
        avg_px: Optional[float] = None

        while time.monotonic() <= deadline:
            try:
                resp = requests.get(url, headers=headers, params={"order_id": order_id}, timeout=5)
                if resp.status_code == 200:
                    data = resp.json().get("data") or {}
                    last_status = str(data.get("status") or "").strip().lower()
                    avg_px = _to_float(data.get("average_price"))
                    if last_status == "complete":
                        return last_status, avg_px
                    if last_status in ("rejected", "cancelled"):
                        return last_status, avg_px
            except Exception:
                pass
            time.sleep(0.35)
        return last_status, avg_px

    def _cancel_order(self, order_id: str) -> None:
        url = "https://api.upstox.com/v2/order/cancel"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.access_token}"}
        try:
            requests.delete(url, headers=headers, params={"order_id": order_id}, timeout=5)
        except Exception:
            pass

    def _place_v3_order(
        self,
        instrument_key: str,
        qty: int,
        transaction_type: str,
        order_type: str,
        limit_price: float,
    ) -> Tuple[bool, Optional[str], str]:
        try:
            body = upstox_client.PlaceOrderV3Request(
                quantity=int(qty),
                product=config.PRODUCT_TYPE,
                validity="DAY",
                price=float(limit_price if order_type == "LIMIT" else 0.0),
                tag=config.ORDER_TAG,
                instrument_token=str(instrument_key),
                order_type=order_type,
                transaction_type=transaction_type,
                disclosed_quantity=0,
                trigger_price=0.0,
                is_amo=False,
                slice=False,
            )
            resp = self.order_api.place_order(body, algo_name=config.ALGO_NAME)
            data = getattr(resp, "data", None)
            order_ids = getattr(data, "order_ids", None)
            order_id = None
            if isinstance(order_ids, list) and order_ids:
                order_id = str(order_ids[0])
            elif getattr(data, "order_id", None):
                order_id = str(getattr(data, "order_id"))
            return True, order_id, "ok"
        except ApiException as exc:
            return False, None, f"ApiException {exc.status}: {exc.body or exc.reason}"
        except Exception as exc:
            return False, None, str(exc)

    def _execute_leg_order(
        self,
        instrument_key: str,
        symbol: str,
        qty: int,
        ltp: float,
        transaction_type: str,
        pos_mode: str,
        urgent: bool = False,
    ) -> Tuple[bool, float, Optional[str]]:
        """Execute a single BUY or SELL option leg via Practice simulation or Upstox OrderApiV3."""
        if pos_mode == "P":
            if transaction_type == "BUY":
                fill = round(ltp + config.PRACTICE_SLIPPAGE_PTS, 2)
                return True, fill, f"PRACTICE_BUY_{int(time.time())}"
            fill = max(0.05, round(ltp - config.PRACTICE_SLIPPAGE_PTS, 2))
            return True, fill, f"PRACTICE_SELL_{int(time.time())}"

        limit_price = (
            round(ltp + config.MPP_BUFFER_PTS, 1)
            if transaction_type == "BUY"
            else max(0.05, round(ltp - config.MPP_BUFFER_PTS, 1))
        )
        ok, order_id, err = self._place_v3_order(
            instrument_key=instrument_key,
            qty=qty,
            transaction_type=transaction_type,
            order_type="LIMIT",
            limit_price=limit_price,
        )
        if ok and order_id:
            status, avg_px = self._poll_order_details(order_id, timeout_secs=1.8 if not urgent else 1.2)
            if status == "complete":
                return True, round(avg_px if (avg_px and avg_px > 0) else ltp, 2), order_id
            if not urgent:
                if status in ("rejected", "cancelled"):
                    self.log_event(f"[ORDER REJECTED] {transaction_type} {symbol} ({order_id}) {status}.")
                    return False, 0.0, order_id
                if status in ("open", "pending", "trigger pending", "put order req received"):
                    self.log_event(f"[ORDER TIMEOUT] Unfilled LIMIT {transaction_type} {order_id}; cancelling.")
                    self._cancel_order(order_id)
                    return False, 0.0, order_id
                return True, round(avg_px if (avg_px and avg_px > 0) else ltp, 2), order_id
            else:
                self.log_event(
                    f"[EXIT FALLBACK] LIMIT {transaction_type} {order_id} status={status}; firing MARKET!"
                )
                if status not in ("rejected", "cancelled"):
                    self._cancel_order(order_id)
        elif not ok:
            if not urgent:
                self.log_event(f"[ORDER REJECTED] {transaction_type} {symbol} failed: {err}")
                return False, 0.0, None
            self.log_event(f"[EXIT FALLBACK] LIMIT {transaction_type} error ({err}); firing MARKET on {symbol}!")

        if urgent:
            ok_mkt, mkt_id, mkt_err = self._place_v3_order(
                instrument_key=instrument_key,
                qty=qty,
                transaction_type=transaction_type,
                order_type="MARKET",
                limit_price=0.0,
            )
            if ok_mkt and mkt_id:
                _, avg_px = self._poll_order_details(mkt_id, timeout_secs=1.5)
                return True, round(avg_px if (avg_px and avg_px > 0) else ltp, 2), mkt_id
            self.log_event(f"[CRITICAL] MARKET {transaction_type} failed for {symbol}: {mkt_err}")
            return False, round(ltp, 2), mkt_id

        return True, round(ltp, 2), order_id

    def _execute_entry_order(self, contract: OptionContract, ltp: float, qty: int) -> Tuple[bool, float, Optional[str]]:
        return self._execute_leg_order(
            instrument_key=contract.instrument_key,
            symbol=contract.trading_symbol,
            qty=qty,
            ltp=ltp,
            transaction_type="BUY",
            pos_mode=self.mode,
            urgent=False,
        )

    def _execute_spread_entry(
        self,
        long_contract: OptionContract,
        long_ltp: float,
        short_contract: OptionContract,
        short_ltp: float,
        qty: int,
    ) -> Tuple[bool, bool, float, float, Optional[str], Optional[str]]:
        """
        SEBI Margin-Safe Hedge Entry:
          1. BUY long ATM leg FIRST and confirm fill.
          2. SELL short OTM (+150/-150) hedge wing SECOND.
        Returns (entry_ok, is_hedged, long_fill, short_fill, long_oid, short_oid).
        """
        ok_long, long_fill, long_oid = self._execute_leg_order(
            instrument_key=long_contract.instrument_key,
            symbol=long_contract.trading_symbol,
            qty=qty,
            ltp=long_ltp,
            transaction_type="BUY",
            pos_mode=self.mode,
            urgent=False,
        )
        if not ok_long:
            return False, False, 0.0, 0.0, long_oid, None

        ok_short, short_fill, short_oid = self._execute_leg_order(
            instrument_key=short_contract.instrument_key,
            symbol=short_contract.trading_symbol,
            qty=qty,
            ltp=short_ltp,
            transaction_type="SELL",
            pos_mode=self.mode,
            urgent=False,
        )
        if not ok_short:
            self.log_event(
                f"[HEDGE WARN] Long BUY filled ({long_contract.trading_symbol} @ ₹{long_fill:.2f}), "
                f"but short hedge {short_contract.trading_symbol} failed; managing as NAKED_DIRECTIONAL."
            )
            return True, False, long_fill, 0.0, long_oid, short_oid

        return True, True, long_fill, short_fill, long_oid, short_oid

    def _execute_exit_order(
        self, instrument_key: str, symbol: str, qty: int, ltp: float, pos_mode: str, urgent: bool
    ) -> Tuple[float, Optional[str]]:
        _, fill_px, oid = self._execute_leg_order(
            instrument_key=instrument_key,
            symbol=symbol,
            qty=qty,
            ltp=ltp,
            transaction_type="SELL",
            pos_mode=pos_mode,
            urgent=urgent,
        )
        return fill_px, oid

    def _execute_spread_exit(
        self,
        long_key: str,
        long_symbol: str,
        long_ltp: float,
        short_key: str,
        short_symbol: str,
        short_ltp: float,
        qty: int,
        pos_mode: str,
    ) -> Tuple[float, float]:
        """
        SEBI Margin-Safe Hedge Exit:
          1. BUY back short OTM hedge leg FIRST to avoid peak-margin penalties.
          2. SELL long ATM leg SECOND.
        """
        _, short_buyback, _ = self._execute_leg_order(
            instrument_key=short_key,
            symbol=short_symbol,
            qty=qty,
            ltp=short_ltp,
            transaction_type="BUY",
            pos_mode=pos_mode,
            urgent=True,
        )
        _, long_sell, _ = self._execute_leg_order(
            instrument_key=long_key,
            symbol=long_symbol,
            qty=qty,
            ltp=long_ltp,
            transaction_type="SELL",
            pos_mode=pos_mode,
            urgent=True,
        )
        return long_sell, short_buyback

    # ------------------------------------------------------------------
    # STRATEGY, CONFLUENCE SCORING, AUTO-HEDGING & RISK LOGIC
    # ------------------------------------------------------------------

    def _find_hedge_wing(self, contract: OptionContract) -> Optional[OptionContract]:
        if not config.ALLOW_HEDGING:
            return None
        wing_strike = (
            contract.strike_price + config.HEDGE_WING_OFFSET
            if contract.option_type == "CE"
            else contract.strike_price - config.HEDGE_WING_OFFSET
        )
        return self.contracts_by_strike_type.get((round(wing_strike, 2), contract.option_type))

    def _evaluate_entries(self, ts: datetime) -> None:
        with self.lock:
            if self.open_position is not None:
                return
            if self.kill_switch_triggered or self.realized_net_pnl <= config.MAX_DAILY_LOSS_INR:
                return
            if not config.UNLIMITED_TRADES and self.trade_count >= config.MAX_TRADES_PER_DAY:
                return
            t = ts.time()
            if t < INITIAL_ORB_END_TIME or t >= LAST_NEW_ENTRY_TIME:
                return
            if self.last_exit_time is not None:
                if (ts - self.last_exit_time).total_seconds() < config.REENTRY_COOLDOWN_SECS:
                    return

            res = evaluate_all_weather_entry(
                spot_series=self.spot_series,
                contracts=self.watched_contracts,
                option_series_map=self.option_series,
                wallet_capital=config.WALLET_CAPITAL,
                lots=config.LOTS_PER_TRADE,
                min_premium=15.0,
            )
            if res is None:
                return

            best_contract, entry_ltp, strategy_name, opt_ind = res
            spot_ltp = float(self.spot_series.last_ltp or 0.0)
            lots = config.LOTS_PER_TRADE
            qty = best_contract.lot_size * lots

            wing_contract = self._find_hedge_wing(best_contract) if config.ALLOW_HEDGING else None
            wing_series = (
                self.option_series.get(wing_contract.instrument_key)
                if wing_contract is not None
                else None
            )
            wing_ltp = wing_series.last_ltp if (wing_series and wing_series.last_ltp and wing_series.last_ltp > 0) else None

            if config.ALLOW_HEDGING and wing_contract is not None and wing_ltp is not None and entry_ltp > wing_ltp:
                ok, is_hedged, long_fill, short_fill, long_oid, _ = self._execute_spread_entry(
                    long_contract=best_contract,
                    long_ltp=entry_ltp,
                    short_contract=wing_contract,
                    short_ltp=wing_ltp,
                    qty=qty,
                )
                if not ok:
                    return
            else:
                is_hedged = False
                ok, long_fill, long_oid = self._execute_entry_order(best_contract, entry_ltp, qty)
                if not ok:
                    return
                short_fill = 0.0
                wing_contract = None

            if is_hedged and wing_contract is not None:
                net_entry = round(long_fill - short_fill, 2)
                raw_spread = round(entry_ltp - (wing_ltp or 0.0), 2)
                sl_price = round(net_entry - config.INITIAL_SL_PTS, 2)
                charges = round(config.BROKERAGE_AND_TAX_PER_TRADE * 2.0, 2)
                self.open_position = {
                    "mode": self.mode,
                    "strategy_mode": "HEDGED_DEBIT_SPREAD",
                    "strategy_name": strategy_name,
                    "instrument_key": best_contract.instrument_key,
                    "trading_symbol": best_contract.trading_symbol,
                    "short_instrument_key": wing_contract.instrument_key,
                    "short_trading_symbol": wing_contract.trading_symbol,
                    "short_strike": wing_contract.strike_price,
                    "option_type": best_contract.option_type,
                    "strike": best_contract.strike_price,
                    "lot_size": best_contract.lot_size,
                    "lots": lots,
                    "qty": qty,
                    "entry_price": net_entry,
                    "long_entry_price": long_fill,
                    "short_entry_price": short_fill,
                    "entry_time": ts.isoformat(),
                    "spot_entry": round(spot_ltp, 2),
                    "highest_ltp": raw_spread,
                    "sl_price": sl_price,
                    "charges": charges,
                    "step1_logged": False,
                    "step2_logged": False,
                    "dynamic_logged": False,
                    "order_id": long_oid,
                    "trigger_reason": strategy_name,
                }
                self._save_state()
                self.log_event(
                    f"ENTRY [{self.mode}][SPREAD] BUY {best_contract.trading_symbol} @ ₹{long_fill:.2f} / "
                    f"SELL {wing_contract.trading_symbol} @ ₹{short_fill:.2f} | Net: ₹{net_entry:.2f} | "
                    f"Init SL: ₹{sl_price:.2f} | {strategy_name}"
                )
            else:
                sl_price = round(long_fill - config.INITIAL_SL_PTS, 2)
                charges = round(config.FLAT_BROKERAGE_ROUND + config.STATUTORY_TAX_PER_LOT * lots, 2)
                self.open_position = {
                    "mode": self.mode,
                    "strategy_mode": "SINGLE_LEG_SCALP",
                    "strategy_name": strategy_name,
                    "instrument_key": best_contract.instrument_key,
                    "trading_symbol": best_contract.trading_symbol,
                    "short_instrument_key": None,
                    "short_trading_symbol": None,
                    "option_type": best_contract.option_type,
                    "strike": best_contract.strike_price,
                    "lot_size": best_contract.lot_size,
                    "lots": lots,
                    "qty": qty,
                    "entry_price": long_fill,
                    "long_entry_price": long_fill,
                    "short_entry_price": 0.0,
                    "entry_time": ts.isoformat(),
                    "spot_entry": round(spot_ltp, 2),
                    "highest_ltp": entry_ltp,
                    "sl_price": sl_price,
                    "charges": charges,
                    "step1_logged": False,
                    "step2_logged": False,
                    "dynamic_logged": False,
                    "order_id": long_oid,
                    "trigger_reason": strategy_name,
                }
                self._save_state()
                self.log_event(
                    f"ENTRY [{self.mode}] {best_contract.trading_symbol} | Qty:{qty} | "
                    f"Buy: ₹{long_fill:.2f} | Init SL: ₹{sl_price:.2f} | Spot: {spot_ltp:.2f} | "
                    f"RSI5: {opt_ind.get('rsi5') or 0:.1f} | {strategy_name}"
                )

    def _current_position_value(self, pos: Dict[str, Any]) -> Optional[float]:
        long_key = str(pos["instrument_key"])
        long_ltp = self.option_series[long_key].last_ltp if long_key in self.option_series else None
        if long_ltp is None or long_ltp <= 0:
            return None
        if pos.get("strategy_mode") == "HEDGED_DEBIT_SPREAD" and pos.get("short_instrument_key"):
            short_key = str(pos["short_instrument_key"])
            short_ltp = self.option_series[short_key].last_ltp if short_key in self.option_series else None
            if short_ltp is None:
                return None
            return round(long_ltp - short_ltp, 2)
        return long_ltp

    def _manage_open_position(self, current_val: float, ts: datetime) -> None:
        with self.lock:
            pos = self.open_position
            if pos is None:
                return

            entry_price = float(pos["entry_price"])
            qty = int(pos["qty"])
            charges = float(pos.get("charges") or config.BROKERAGE_AND_TAX_PER_TRADE)
            old_sl = float(pos["sl_price"])

            entry_dt = datetime.fromisoformat(pos["entry_time"])
            if entry_dt.tzinfo is None:
                entry_dt = IST.localize(entry_dt)
            minutes_held = (ts - entry_dt).total_seconds() / 60.0

            new_high, new_sl, exit_reason, target_exit_px = evaluate_micro_scalp_exit(
                entry_price=entry_price,
                current_ltp=current_val,
                highest_ltp=float(pos["highest_ltp"]),
                sl_price=old_sl,
                minutes_held=minutes_held,
                ts_time=ts.time(),
                realized_day_net_pnl=self.realized_net_pnl,
                qty=qty,
                charges=charges,
                max_daily_loss_inr=config.MAX_DAILY_LOSS_INR,
            )

            pos["highest_ltp"] = new_high
            pos["sl_price"] = new_sl
            peak_gain = new_high - entry_price
            sl_updated = new_sl > old_sl

            if peak_gain >= config.BREAKEVEN_TRIGGER_PTS and not pos.get("step1_logged"):
                pos["step1_logged"] = True
                sl_updated = True
                self.log_event(
                    f"[BREAKEVEN SHIELD (+3.2 pts)] {pos['trading_symbol']} High: ₹{new_high:.2f} -> "
                    f"SL locked at ₹{new_sl:.2f} (Risk-free after brokerage)"
                )
            if peak_gain >= config.QUICK_LOCK_TRIGGER_PTS and not pos.get("step2_logged"):
                pos["step2_logged"] = True
                sl_updated = True
                self.log_event(
                    f"[QUICK LOCK (+5.0 pts)] {pos['trading_symbol']} High: ₹{new_high:.2f} -> "
                    f"SL moved to ₹{new_sl:.2f} (+4.0 pts locked)"
                )
            if peak_gain >= config.MICRO_TRAIL_TRIGGER_PTS and not pos.get("dynamic_logged"):
                pos["dynamic_logged"] = True
                sl_updated = True
                self.log_event(
                    f"[MICRO TRAIL (+6.5 pts+)] {pos['trading_symbol']} High: ₹{new_high:.2f} -> "
                    f"Trailing SL at ₹{new_sl:.2f} (High - 1.0 pt)"
                )

            if sl_updated:
                self._save_state()

            if exit_reason is not None:
                exit_val = target_exit_px if (exit_reason == "QUICK_TARGET_HIT" and self.mode == "P" and target_exit_px) else current_val
                self._close_position(exit_val, ts, exit_reason)

    def _close_position(self, current_val: float, ts: datetime, exit_reason: str) -> None:
        pos = self.open_position
        if pos is None:
            return

        pos_mode = str(pos.get("mode") or self.mode)
        is_spread = pos.get("strategy_mode") == "HEDGED_DEBIT_SPREAD" and bool(pos.get("short_instrument_key"))
        inst_key = str(pos["instrument_key"])
        symbol = str(pos["trading_symbol"])
        qty = int(pos["qty"])
        entry_price = float(pos["entry_price"])
        highest_ltp = float(pos["highest_ltp"])
        spot_entry = float(pos.get("spot_entry") or 0.0)
        spot_exit = float(self.spot_series.last_ltp or spot_entry)
        charges = float(pos.get("charges") or config.BROKERAGE_AND_TAX_PER_TRADE)

        if is_spread:
            short_key = str(pos["short_instrument_key"])
            short_symbol = str(pos.get("short_trading_symbol") or short_key)
            long_ltp = (
                self.option_series[inst_key].last_ltp
                if inst_key in self.option_series and self.option_series[inst_key].last_ltp
                else float(pos.get("long_entry_price") or entry_price)
            )
            short_ltp = (
                self.option_series[short_key].last_ltp
                if short_key in self.option_series and self.option_series[short_key].last_ltp is not None
                else float(pos.get("short_entry_price") or 0.0)
            )
            long_sell, short_buyback = self._execute_spread_exit(
                long_key=inst_key,
                long_symbol=symbol,
                long_ltp=long_ltp,
                short_key=short_key,
                short_symbol=short_symbol,
                short_ltp=short_ltp,
                qty=qty,
                pos_mode=pos_mode,
            )
            sell_price = round(long_sell - short_buyback, 2)
            display_sym = f"{symbol} / -{short_symbol}"
        elif pos_mode == "P" and exit_reason == "QUICK_TARGET_HIT":
            sell_price = round(entry_price + config.INSTANT_TAKE_PROFIT_PTS, 2)
            display_sym = symbol
        else:
            sell_price, _ = self._execute_exit_order(
                instrument_key=inst_key,
                symbol=symbol,
                qty=qty,
                ltp=current_val,
                pos_mode=pos_mode,
                urgent=True,
            )
            display_sym = symbol

        points_captured = round(sell_price - entry_price, 2)
        gross_pnl = round(points_captured * qty, 2)
        net_pnl = round(gross_pnl - charges, 2)
        self.realized_net_pnl = round(self.realized_net_pnl + net_pnl, 2)
        self.trade_count += 1
        self.last_exit_time = ts

        if exit_reason in ("EMERGENCY_STOP_5000", "DAILY_KILL_SWITCH") or self.realized_net_pnl <= config.MAX_DAILY_LOSS_INR:
            self.kill_switch_triggered = True

        entry_dt = datetime.fromisoformat(pos["entry_time"])
        if entry_dt.tzinfo is None:
            entry_dt = IST.localize(entry_dt)

        self._append_trade_csv([
            ts.strftime("%Y-%m-%d"),
            pos_mode,
            display_sym,
            inst_key,
            entry_dt.strftime("%H:%M:%S"),
            ts.strftime("%H:%M:%S"),
            qty,
            f"{spot_entry:.2f}",
            f"{spot_exit:.2f}",
            f"{entry_price:.2f}",
            f"{sell_price:.2f}",
            f"{highest_ltp:.2f}",
            f"{points_captured:.2f}",
            f"{gross_pnl:.2f}",
            f"{charges:.2f}",
            f"{net_pnl:.2f}",
            f"{self.realized_net_pnl:.2f}",
            exit_reason,
        ])

        self.open_position = None
        self._save_state()

        self.log_event(
            f"EXIT [{pos_mode}] {display_sym} | Reason: {exit_reason} | "
            f"Exit: ₹{sell_price:.2f} (Entry: ₹{entry_price:.2f}) | Pts: {points_captured:+.2f} | "
            f"Net P&L: ₹{net_pnl:+,.2f} | Day Net: ₹{self.realized_net_pnl:+,.2f}"
        )
        if self.kill_switch_triggered:
            self.log_event(
                f"[KILL-SWITCH ACTIVATED] Daily Net P&L ₹{self.realized_net_pnl:+,.2f} <= "
                f"₹{config.MAX_DAILY_LOSS_INR:,.2f}. Bot locked for today."
            )

    # ------------------------------------------------------------------
    # WEBSOCKET V3 CALLBACKS
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_tick_fields(data: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        ff = data.get("ff") or {}
        market_ff = ff.get("marketFF") or {}
        index_ff = ff.get("indexFF") or {}

        ltpc = market_ff.get("ltpc") or {}
        ltp = _to_float(ltpc.get("ltp"))
        if ltp is None:
            idx_ltpc = index_ff.get("ltpc") or {}
            ltp = _to_float(idx_ltpc.get("ltp"))
            if ltp is not None:
                ltpc = idx_ltpc
        if ltp is None:
            top_ltpc = data.get("ltpc") or {}
            ltp = _to_float(top_ltpc.get("ltp"))
            if ltp is not None:
                ltpc = top_ltpc

        if ltp is None or ltp <= 0:
            return None, None, None, None

        e_feed = market_ff.get("eFeedDetails") or {}
        vtt = _to_float(market_ff.get("vtt") if market_ff.get("vtt") is not None else e_feed.get("vtt"))
        oi = _to_float(market_ff.get("oi") if market_ff.get("oi") is not None else e_feed.get("oi"))
        ltq = _to_float(ltpc.get("ltq"))
        return ltp, vtt, oi, ltq

    def _on_open(self, *args: Any) -> None:
        self.ws_connected = True
        self.log_event(
            f"[WS V3 CONNECTED] Subscribed to Spot + {len(self.option_series)} option contract(s)."
        )

    def _on_error(self, *args: Any) -> None:
        err = args[0] if args else "Unknown WebSocket error"
        self.log_event(f"[WS V3 ERROR] {err}")

    def _on_close(self, *args: Any) -> None:
        self.ws_connected = False
        if not self.stop_event.is_set():
            self.log_event("[WS V3 DISCONNECTED] Auto-reconnect active...")

    def _on_message(self, msg: Any, *args: Any) -> None:
        if self.stop_event.is_set():
            return
        if isinstance(msg, (str, bytes)):
            try:
                msg = json.loads(msg)
            except Exception:
                return
        if not isinstance(msg, dict):
            return

        feeds = msg.get("feeds") or {}
        if not isinstance(feeds, dict) or not feeds:
            return

        ts = now_ist()
        active_pos_tick_updated = False

        with self.lock:
            for key, data in feeds.items():
                if not isinstance(data, dict):
                    continue
                ltp, vtt, oi, ltq = self._extract_tick_fields(data)
                if ltp is None:
                    continue

                if key == config.SPOT_KEY:
                    self.spot_series.on_tick(ltp, ts, vtt=vtt, oi=oi, ltq=ltq)
                    orb_msg = self.orb.on_spot_tick(ltp, ts)
                    if orb_msg:
                        self._save_state()
                        self.log_event(orb_msg)
                elif key in self.option_series:
                    self.option_series[key].on_tick(ltp, ts, vtt=vtt, oi=oi, ltq=ltq)
                    if self.open_position and key in (
                        self.open_position.get("instrument_key"),
                        self.open_position.get("short_instrument_key"),
                    ):
                        active_pos_tick_updated = True

            if self.open_position is not None and active_pos_tick_updated:
                cur_val = self._current_position_value(self.open_position)
                if cur_val is not None:
                    self._manage_open_position(cur_val, ts)
            elif self.open_position is None:
                self._evaluate_entries(ts)

    # ------------------------------------------------------------------
    # CONSOLE DASHBOARD & MAIN LOOP
    # ------------------------------------------------------------------

    def _render_dashboard_line(self) -> None:
        ts = now_ist()
        with self.lock:
            spot_str = f"{self.spot_series.last_ltp:.2f}" if self.spot_series.last_ltp else "--"
            strikes_parts = []
            for key, c in self.watched_contracts.items():
                short_sym = f"{int(c.strike_price) if c.strike_price.is_integer() else c.strike_price}{c.option_type}"
                ltp = self.option_series[key].last_ltp if key in self.option_series else None
                ltp_str = f"{ltp:.1f}" if ltp else "--"
                strikes_parts.append(f"{short_sym}:{ltp_str}")
            watched_str = " ".join(strikes_parts)

            if self.open_position is not None:
                pos = self.open_position
                cur_val = self._current_position_value(pos)
                entry_px = float(pos["entry_price"])
                if cur_val is None:
                    cur_val = entry_px
                qty = int(pos["qty"])
                charges = float(pos.get("charges") or config.BROKERAGE_AND_TAX_PER_TRADE)
                trade_pnl = ((cur_val - entry_px) * qty) - charges
                day_net = self.realized_net_pnl + trade_pnl
                label = pos["trading_symbol"]
                if pos.get("short_trading_symbol"):
                    label = f"{label}/-{pos['short_trading_symbol']}"
                trade_str = (
                    f"{label} @ {entry_px:.2f} | "
                    f"Val:{cur_val:.2f} | High:{float(pos['highest_ltp']):.2f} | "
                    f"Trail SL:{float(pos['sl_price']):.2f} | Trade P&L:₹{trade_pnl:+,.2f}"
                )
            else:
                day_net = self.realized_net_pnl
                if self.kill_switch_triggered:
                    trade_str = "HALTED (EMERGENCY STOP)"
                elif not config.UNLIMITED_TRADES and self.trade_count >= config.MAX_TRADES_PER_DAY:
                    trade_str = f"DAILY CAP REACHED ({config.MAX_TRADES_PER_DAY})"
                elif ts.time() >= HARD_SQUARE_OFF_TIME:
                    trade_str = "EOD CLOSED"
                elif ts.time() >= LAST_NEW_ENTRY_TIME:
                    trade_str = "NO NEW ENTRIES (>15:15)"
                elif ts.time() < MARKET_OPEN_TIME:
                    trade_str = "PRE-OPEN WAIT"
                elif not self.orb.orb_ready:
                    trade_str = "BUILDING 5m ORB"
                else:
                    trade_str = f"SCANNING (ORB {self.orb.orb_low:.0f}-{self.orb.orb_high:.0f})"

            trade_cap_str = (
                f"{self.trade_count}"
                if config.UNLIMITED_TRADES
                else f"{self.trade_count}/{config.MAX_TRADES_PER_DAY}"
            )
            line = (
                f"[{ts.strftime('%H:%M:%S')}] | Mode:{self.mode} | Spot:{spot_str} | "
                f"{watched_str} | Active: {trade_str} | "
                f"Day Net:₹{day_net:+,.2f} | Trades:{trade_cap_str}"
            )

        with self.print_lock:
            sys.stdout.write(f"\r\x1b[2K{line}")
            sys.stdout.flush()

    def _start_streamer(self) -> None:
        instrument_keys = [config.SPOT_KEY] + list(self.option_series.keys())
        self.streamer = upstox_client.MarketDataStreamerV3(self.api_client, instrument_keys, "full")
        self.streamer.on("open", self._on_open)
        self.streamer.on("message", self._on_message)
        self.streamer.on("error", self._on_error)
        try:
            self.streamer.on("close", self._on_close)
        except Exception:
            pass
        self.streamer.auto_reconnect(True, 5, 10)
        self.streamer.connect()

    def run(self) -> None:
        ws_thread = threading.Thread(target=self._start_streamer, daemon=True)
        ws_thread.start()

        self.log_event(
            f"[BOT STARTED] Mode={self.mode} | Capital=₹{config.WALLET_CAPITAL:,.0f} | "
            f"Emergency Stop=₹{config.MAX_DAILY_LOSS_INR:,.0f} | Max Trades={config.MAX_TRADES_PER_DAY}"
        )

        try:
            while not self.stop_event.is_set():
                ts = now_ist()
                with self.lock:
                    orb_msg = self.orb.refresh_state(ts.time())
                    if orb_msg:
                        self._save_state()
                        self.log_event(orb_msg)

                    # Enforce time-based & emergency-stop checks every second even between ticks
                    if self.open_position is not None:
                        cur_val = self._current_position_value(self.open_position)
                        if cur_val is not None:
                            self._manage_open_position(cur_val, ts)

                self._render_dashboard_line()
                self.stop_event.wait(1.0)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.stop_event.set()
        if self.streamer is not None and hasattr(self.streamer, "disconnect"):
            try:
                self.streamer.disconnect()
            except Exception:
                pass
        with self.lock:
            self._save_state()
        with self.print_lock:
            sys.stdout.write("\n")
            sys.stdout.flush()
        self.log_event("[SHUTDOWN] State saved cleanly to state.json. Goodbye!")


def main() -> None:
    print("\n" + "=" * 72)
    print("  ANTIGRAVITY NIFTY 50 MOMENTUM & ORB SCALPER (UPSTOX V3)")
    print("=" * 72)

    access_token = run_step_a_login()
    mode = run_step_b_mode()

    expiry_date, weekly_contracts = load_nifty_weekly_options()
    all_contracts_by_key = {c.instrument_key: c for c in weekly_contracts}
    spot_ltp = fetch_spot_ltp(access_token)

    watched_contracts = run_step_c_strikes(access_token, spot_ltp, expiry_date, weekly_contracts)
    bot = NiftyScalperBot(
        access_token=access_token,
        mode=mode,
        watched_contracts=watched_contracts,
        all_contracts_by_key=all_contracts_by_key,
    )

    def _handle_sigint(signum: int, frame: Any) -> None:
        bot.stop_event.set()

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    bot.run()


if __name__ == "__main__":
    main()
