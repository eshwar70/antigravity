#!/usr/bin/env python3
"""Strictly causal real-market snapshot builder from cached Upstox 1-minute data.

Zero future leakage:
- At minute boundary t (e.g. 09:20:00 IST), ONLY completed bars strictly before t (<= 09:19:00)
  are included in `bars`.
- Live spot, VIX, breadth, and option quote marks at t use minute t's OPEN (observed at t+00s),
  never minute t's high/low/close.
- Option volume (cumulative) and OI come strictly from completed minute t-1.
- Black-Scholes implied volatility & Greeks are fitted strictly from completed minute t-1 close.
- Two snapshots are emitted per minute (t+00s and t+02.5s) to preserve the exact two-step causal
  signal -> next-snapshot fill model of Winner of 51.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta, timezone
import gzip
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

IST = timezone(timedelta(hours=5, minutes=30))
INDEX = "NSE_INDEX|Nifty 50"
ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "market_cache"
MEMBERSHIP_PATH = ROOT.parent / "bots" / "nifty_membership.json"

RISK_FREE = 0.06
SPREAD_HALF = 0.005  # 1.0% total bid-ask spread (matching winner51_benchmark.json)


def load_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price_and_greeks(
    spot: float,
    strike: float,
    t_years: float,
    iv: float,
    kind: str,
    r: float = RISK_FREE,
) -> Tuple[float, dict]:
    t = max(t_years, 1.0 / (365.0 * 24.0 * 60.0))
    sig = max(0.05, min(1.50, iv))
    sqt = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * sig * sig) * t) / (sig * sqt)
    d2 = d1 - sig * sqt
    disc = math.exp(-r * t)
    pdf = _norm_pdf(d1)
    if kind == "CE":
        nd1 = _norm_cdf(d1)
        nd2 = _norm_cdf(d2)
        price = spot * nd1 - strike * disc * nd2
        delta = nd1
        theta_ann = -(spot * pdf * sig) / (2.0 * sqt) - r * strike * disc * nd2
    else:
        nmd1 = _norm_cdf(-d1)
        nmd2 = _norm_cdf(-d2)
        price = strike * disc * nmd2 - spot * nmd1
        delta = nd1_p = _norm_cdf(d1) - 1.0
        theta_ann = -(spot * pdf * sig) / (2.0 * sqt) + r * strike * disc * nmd2
    gamma = pdf / (spot * sig * sqt)
    vega = spot * pdf * sqt / 100.0  # per 1% IV change
    theta_day = theta_ann / 365.0
    return price, {
        "delta": round(delta, 5),
        "gamma": round(gamma, 6),
        "theta": round(theta_day, 4),
        "vega": round(vega, 4),
        "iv": round(sig * 100.0, 2),
    }


def fit_bs_iv(spot: float, strike: float, t_years: float, market_price: float, kind: str, fallback_iv: float) -> float:
    intrinsic = max(0.0, spot - strike) if kind == "CE" else max(0.0, strike - spot)
    if market_price <= intrinsic + 0.05:
        return max(0.06, min(0.45, fallback_iv))
    lo, hi = 0.05, 0.90
    for _ in range(18):
        mid = 0.5 * (lo + hi)
        p, _ = bs_price_and_greeks(spot, strike, t_years, mid, kind)
        if p > market_price:
            hi = mid
        else:
            lo = mid
    iv = 0.5 * (lo + hi)
    return max(0.06, min(0.80, iv))


class MarketDataset:
    """Loads cached real Upstox 1-minute data once and yields strictly causal snapshots."""

    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.manifest = load_gz(cache_dir / "manifest.json.gz")
        self.membership = json.loads(MEMBERSHIP_PATH.read_text(encoding="utf-8"))
        self.trading_days: List[str] = self.manifest["trading_days"]
        self.day_to_expiry: Dict[str, str] = self.manifest["day_to_expiry"]
        self.contracts_meta: Dict[str, List[dict]] = self.manifest["contracts_meta"]

        # Load NIFTY 50 bars
        raw_nifty = load_gz(cache_dir / "nifty_1m.json.gz")
        self.nifty_all: List[dict] = []
        self.nifty_by_day: Dict[str, List[dict]] = {}
        self.nifty_ts_map: Dict[str, dict] = {}
        for r in raw_nifty:
            ts = r[0]
            hhmm = ts[11:16]
            if not ("09:15" <= hhmm <= "15:29"):
                continue
            bar = dict(
                timestamp=ts,
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=float(r[5] or 0.0),
            )
            self.nifty_all.append(bar)
            self.nifty_by_day.setdefault(ts[:10], []).append(bar)
            self.nifty_ts_map[ts] = bar

        # Index position in nifty_all for fast O(1) sliding window
        self.nifty_idx: Dict[str, int] = {b["timestamp"]: i for i, b in enumerate(self.nifty_all)}

        # Load VIX bars
        raw_vix = load_gz(cache_dir / "vix_1m.json.gz")
        self.vix_map: Dict[str, Tuple[float, float]] = {}  # ts -> (open, close)
        for r in raw_vix:
            self.vix_map[r[0]] = (float(r[1]), float(r[4]))

        # Load all 50 NIFTY constituents
        self.members = self.membership["members"]
        self.const_by_day: Dict[str, Dict[str, Dict[str, Tuple[float, float]]]] = {}
        self.const_day_open: Dict[str, Dict[str, float]] = {}
        self.const_prev_close: Dict[str, Dict[str, float]] = {}
        const_dir = cache_dir / "constituents"
        for m in self.members:
            sym = m["symbol"]
            key = m["key"]
            rows = load_gz(const_dir / f"{sym}.json.gz")
            last_day_close: Optional[float] = None
            by_d: Dict[str, List[list]] = {}
            for r in rows:
                hhmm = r[0][11:16]
                if "09:15" <= hhmm <= "15:29":
                    by_d.setdefault(r[0][:10], []).append(r)
            for d_str in sorted(by_d.keys()):
                drows = by_d[d_str]
                if d_str in self.day_to_expiry:
                    self.const_day_open.setdefault(d_str, {})[key] = float(drows[0][1])
                    self.const_prev_close.setdefault(d_str, {})[key] = (
                        last_day_close if last_day_close is not None else float(drows[0][1])
                    )
                    tmap = self.const_by_day.setdefault(d_str, {}).setdefault(key, {})
                    for r in drows:
                        tmap[r[0]] = (float(r[1]), float(r[2]))
                last_day_close = float(drows[-1][2])

        # Lazy cache of loaded option data per expiry
        self._opt_expiry_cache: Dict[str, Dict[str, Dict[str, list]]] = {}

    def _load_expiry_options(self, expiry: str) -> Tuple[List[dict], Dict[str, Dict[str, list]]]:
        metas = self.contracts_meta[expiry]
        if expiry not in self._opt_expiry_cache:
            opt_dir = self.cache_dir / "options"
            loaded: Dict[str, Dict[str, list]] = {}
            for m in metas:
                sid = f"{expiry}_{int(m['strike'])}_{m['kind']}"
                p = opt_dir / f"{sid}.json.gz"
                if not p.exists():
                    continue
                rows = load_gz(p)
                tmap: Dict[str, list] = {}
                for r in rows:
                    tmap[r[0]] = r  # [ts, o, h, l, c, vol, oi]
                loaded[m["instrument_key"]] = tmap
            self._opt_expiry_cache[expiry] = loaded
        return metas, self._opt_expiry_cache[expiry]

    def build_day_snapshots(self, day_str: str) -> List[dict]:
        """Build all strictly causal snapshots (2 per minute: +0s and +2.5s) for one trading day."""
        day_bars = self.nifty_by_day.get(day_str) or []
        if len(day_bars) < 20:
            return []
        expiry = self.day_to_expiry[day_str]
        exp_dt = datetime.fromisoformat(f"{expiry}T15:30:00+05:30")
        metas, opt_maps = self._load_expiry_options(expiry)

        # Pre-track cumulative completed volume and last completed bar for each option on this day
        cum_vol: Dict[str, float] = {m["instrument_key"]: 0.0 for m in metas}
        last_completed_opt: Dict[str, Optional[list]] = {m["instrument_key"]: None for m in metas}
        last_vix: float = 14.0
        const_day_map = self.const_by_day.get(day_str, {})
        const_opens = self.const_day_open.get(day_str, {})
        const_pclose = self.const_prev_close.get(day_str, {})
        last_const_px: Dict[str, float] = dict(const_opens)

        snapshots: List[dict] = []
        membership_as_of = self.membership["membership_as_of"]

        for i in range(len(day_bars)):
            cur_bar = day_bars[i]
            cur_ts_str = cur_bar["timestamp"]

            # Update completed-minute option volume & last completed bar from i-1
            if i >= 1:
                prev_bar = day_bars[i - 1]
                prev_ts_str = prev_bar["timestamp"]
                for m in metas:
                    okey = m["instrument_key"]
                    orow = opt_maps.get(okey, {}).get(prev_ts_str)
                    if orow is not None:
                        cum_vol[okey] += float(orow[5] or 0.0)
                        last_completed_opt[okey] = orow

            # Need at least 1 completed bar on current day (start from index 1 -> 09:16:00)
            if i == 0:
                v_pair = self.vix_map.get(cur_ts_str)
                if v_pair:
                    last_vix = v_pair[0]
                continue

            prev_bar = day_bars[i - 1]
            prev_ts_str = prev_bar["timestamp"]
            global_prev_idx = self.nifty_idx[prev_ts_str]
            start_idx = max(0, global_prev_idx - 179)
            completed_bars = self.nifty_all[start_idx : global_prev_idx + 1]
            if len(completed_bars) < 60:
                continue

            t_dt = datetime.fromisoformat(cur_ts_str)
            spot_open = cur_bar["open"]
            prev_spot_close = prev_bar["close"]

            # VIX at minute open (causal)
            v_pair = self.vix_map.get(cur_ts_str)
            if v_pair:
                last_vix = v_pair[0]
            fallback_iv = max(0.08, min(0.45, last_vix / 100.0))

            # Constituent breadth at minute open (causal)
            bquotes_template = []
            for m in self.members:
                k = m["key"]
                pair = const_day_map.get(k, {}).get(cur_ts_str)
                if pair:
                    last_const_px[k] = pair[0]
                px = last_const_px.get(k)
                if px and px > 0:
                    bquotes_template.append((k, px, const_pclose.get(k, px), const_opens.get(k, px)))

            # Option quotes at minute open + Greeks strictly from completed minute i-1 close
            t_years = max(1.0 / (365.0 * 24.0 * 60.0), (exp_dt - t_dt).total_seconds() / (365.0 * 24.0 * 3600.0))
            opts_base = []
            for m in metas:
                strike = m["strike"]
                if abs(strike - spot_open) > 650.0:
                    continue
                okey = m["instrument_key"]
                cur_orow = opt_maps.get(okey, {}).get(cur_ts_str)
                prev_orow = last_completed_opt[okey]
                if cur_orow is None or prev_orow is None:
                    continue
                mark = float(cur_orow[1])  # Current minute OPEN (causal)
                if mark <= 0.5:
                    continue
                prev_close_opt = float(prev_orow[4])
                prev_vol = float(prev_orow[5] or 0.0)
                prev_oi = float(prev_orow[6] or 0.0)
                lot = int(m["lot"])
                # Realistic depth from prior completed minute volume
                depth_qty = int(max(lot * 4, prev_vol * 0.02)) if prev_vol >= lot else int(prev_vol)
                iv = fit_bs_iv(prev_spot_close, strike, t_years, prev_close_opt, m["kind"], fallback_iv)
                _, greeks = bs_price_and_greeks(prev_spot_close, strike, t_years, iv, m["kind"])
                bid = round(max(0.05, mark * (1.0 - SPREAD_HALF)), 2)
                ask = round(max(bid, mark * (1.0 + SPREAD_HALF)), 2)
                opts_base.append(
                    dict(
                        key=okey,
                        kind=m["kind"],
                        expiry=expiry,
                        strike=strike,
                        lot=lot,
                        bid=bid,
                        ask=ask,
                        bid_qty=depth_qty,
                        ask_qty=depth_qty,
                        oi=prev_oi,
                        volume=cum_vol[okey],
                        greeks=greeks,
                    )
                )

            # Emit 2 causal snapshots per minute: t+0.0s (signal) and t+2.5s (execution verify)
            for offset_ms in (0, 2500):
                snap_dt = t_dt + timedelta(milliseconds=offset_ms)
                snap_ts = snap_dt.isoformat()
                opts = [{**o, "quote_time": snap_ts} for o in opts_base]
                bquotes = [
                    dict(key=k, timestamp=snap_ts, last=px, previous_close=pc, day_open=do)
                    for (k, px, pc, do) in bquotes_template
                ]
                snapshots.append(
                    dict(
                        timestamp=snap_ts,
                        collected_from=snap_ts,
                        source="upstox-fast-1m-v02",
                        market_status="NORMAL_OPEN",
                        underlying=INDEX,
                        bar_minutes=1,
                        bars=completed_bars,
                        spot_live=dict(timestamp=snap_ts, ltp=spot_open),
                        ticks=[],
                        options=opts,
                        breadth=dict(
                            timestamp=snap_ts,
                            universe="NIFTY50",
                            expected=50,
                            membership_as_of=membership_as_of,
                            quotes=bquotes,
                        ),
                        vix=dict(timestamp=snap_ts, value=last_vix),
                    )
                )
        return snapshots


if __name__ == "__main__":
    import time
    t0 = time.time()
    ds = MarketDataset()
    print(f"Loaded MarketDataset ({len(ds.trading_days)} days) in {time.time()-t0:.2f}s")
    s1 = ds.build_day_snapshots(ds.trading_days[0])
    s_last = ds.build_day_snapshots(ds.trading_days[-1])
    print(f"Day {ds.trading_days[0]}: {len(s1)} snapshots, sample opts={len(s1[10]['options'])}, vix={s1[10]['vix']['value']}")
    print(f"Day {ds.trading_days[-1]}: {len(s_last)} snapshots, sample opts={len(s_last[10]['options'])}, vix={s_last[10]['vix']['value']}")
