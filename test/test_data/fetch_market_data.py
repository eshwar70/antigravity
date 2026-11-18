#!/usr/bin/env python3
"""Download and cache real Upstox 1-minute market data (NIFTY 50, India VIX,
50 NIFTY constituents, and expired/active weekly NIFTY options) for 2026-09-01 to 2026-11-18.

Uses UPSTOX_ACCESS_TOKEN from the environment. Strictly read-only GET requests.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
import gzip
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import urllib.parse
import requests

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "market_cache"
MEMBERSHIP_PATH = ROOT.parent / "bots" / "nifty_membership.json"

INDEX_KEY = "NSE_INDEX|Nifty 50"
VIX_KEY = "NSE_INDEX|India VIX"

START_DATE = "2026-09-01"
WARMUP_START = "2026-08-25"
END_DATE = "2026-11-18"
HIST_END = "2026-11-17"  # Historical endpoint up to yesterday; intraday endpoint for 2026-11-18

CHUNKS = [
    ("2026-08-25", "2026-08-31"),
    ("2026-09-01", "2026-09-30"),
    ("2026-10-01", "2026-10-31"),
    ("2026-11-01", "2026-11-17"),
]

_rate_lock = threading.Lock()
_last_req_ts = 0.0
MIN_INTERVAL = 0.055  # ~18 req/s max polite pacing


def _get_json(session: requests.Session, url: str, headers: dict, retries: int = 5) -> dict:
    global _last_req_ts
    for attempt in range(retries):
        with _rate_lock:
            now = time.monotonic()
            wait = MIN_INTERVAL - (now - _last_req_ts)
            if wait > 0:
                time.sleep(wait)
            _last_req_ts = time.monotonic()
        try:
            resp = session.get(url, headers=headers, timeout=20)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 500, 502, 503, 504):
                backoff = min(15.0, (1.5 ** attempt) * (2.5 if resp.status_code == 429 else 1.0))
                time.sleep(backoff)
                continue
            return {"status": "error", "http": resp.status_code, "text": resp.text[:200]}
        except Exception as exc:
            if attempt == retries - 1:
                return {"status": "error", "exc": str(exc)}
            time.sleep(1.0 * (attempt + 1))
    return {"status": "error", "msg": "max_retries"}


def save_gz_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def load_gz_json(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def fetch_instrument_1m_all(
    session: requests.Session,
    headers: dict,
    inst_key: str,
    chunks: list[tuple[str, str]],
    include_intraday: bool = True,
) -> list[list]:
    enc = urllib.parse.quote(inst_key, safe="")
    by_ts: dict[str, list] = {}
    for s_d, e_d in chunks:
        url = f"https://api.upstox.com/v3/historical-candle/{enc}/minutes/1/{e_d}/{s_d}"
        data = _get_json(session, url, headers)
        for row in (data.get("data") or {}).get("candles") or []:
            by_ts[row[0]] = row
    if include_intraday:
        url = f"https://api.upstox.com/v3/historical-candle/intraday/{enc}/minutes/1"
        data = _get_json(session, url, headers)
        for row in (data.get("data") or {}).get("candles") or []:
            by_ts[row[0]] = row
    return [by_ts[k] for k in sorted(by_ts.keys())]


def main() -> None:
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token:
        print("ERROR: UPSTOX_ACCESS_TOKEN env var is required.", file=sys.stderr)
        sys.exit(1)

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    session = requests.Session()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print("[1/4] Fetching NIFTY 50 & India VIX 1m candles (Aug 25 - Nov 18, 2026)...", flush=True)
    nifty_path = CACHE_DIR / "nifty_1m.json.gz"
    if not nifty_path.exists():
        nifty_bars = fetch_instrument_1m_all(session, headers, INDEX_KEY, CHUNKS, include_intraday=True)
        save_gz_json(nifty_path, nifty_bars)
    else:
        nifty_bars = load_gz_json(nifty_path)

    vix_path = CACHE_DIR / "vix_1m.json.gz"
    if not vix_path.exists():
        vix_bars = fetch_instrument_1m_all(session, headers, VIX_KEY, CHUNKS, include_intraday=True)
        save_gz_json(vix_path, vix_bars)
    else:
        vix_bars = load_gz_json(vix_path)

    # Identify all trading days in [START_DATE, END_DATE]
    day_high_low: dict[str, list[float]] = {}
    for row in nifty_bars:
        d = row[0][:10]
        if START_DATE <= d <= END_DATE:
            hhmm = row[0][11:16]
            if "09:15" <= hhmm <= "15:29":
                if d not in day_high_low:
                    day_high_low[d] = [float(row[3]), float(row[2])]
                else:
                    day_high_low[d][0] = min(day_high_low[d][0], float(row[3]))
                    day_high_low[d][1] = max(day_high_low[d][1], float(row[2]))

    trading_days = sorted(day_high_low.keys())
    print(
        f"    NIFTY bars={len(nifty_bars)}, VIX bars={len(vix_bars)}, "
        f"Trading Sessions ({trading_days[0]}..{trading_days[-1]}): {len(trading_days)}",
        flush=True,
    )

    print("[2/4] Fetching all 50 NIFTY constituent 1m candles...", flush=True)
    membership = json.loads(MEMBERSHIP_PATH.read_text(encoding="utf-8"))
    members = membership["members"]
    const_dir = CACHE_DIR / "constituents"
    const_dir.mkdir(parents=True, exist_ok=True)

    const_chunks = [
        ("2026-08-31", "2026-09-30"),
        ("2026-10-01", "2026-10-31"),
        ("2026-11-01", "2026-11-17"),
    ]

    def fetch_member(m: dict) -> tuple[str, int]:
        sym = m["symbol"]
        key = m["key"]
        out = const_dir / f"{sym}.json.gz"
        if out.exists():
            return sym, len(load_gz_json(out))
        local_sess = requests.Session()
        rows = fetch_instrument_1m_all(local_sess, headers, key, const_chunks, include_intraday=True)
        # Keep only timestamp, open, close (compact for breadth)
        compact = [[r[0], r[1], r[4]] for r in rows]
        save_gz_json(out, compact)
        return sym, len(compact)

    done_c = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_member, m) for m in members]
        for fut in as_completed(futs):
            sym, cnt = fut.result()
            done_c += 1
            if done_c % 10 == 0 or done_c == len(members):
                print(f"    Constituents fetched: {done_c}/{len(members)} (latest {sym}: {cnt} bars)", flush=True)

    print("[3/4] Discovering expired & active weekly NIFTY option contracts...", flush=True)
    exp_resp = _get_json(
        session,
        f"https://api.upstox.com/v2/expired-instruments/expiries?instrument_key={urllib.parse.quote(INDEX_KEY, safe='')}",
        headers,
    )
    expired_exps = sorted(e for e in (exp_resp.get("data") or []) if e >= "2026-09-01")

    act_resp = _get_json(
        session,
        f"https://api.upstox.com/v2/option/contract?instrument_key={urllib.parse.quote(INDEX_KEY, safe='')}",
        headers,
    )
    active_contracts_all = act_resp.get("data") or []
    active_exps = sorted({x["expiry"] for x in active_contracts_all if x["expiry"] <= "2026-12-15"})

    all_exps = sorted(set(expired_exps) | set(active_exps))
    expired_set = set(expired_exps)

    # Map each trading day to the exact expiry FastUpstox selects: 2 <= (exp - day).days <= 14
    day_to_expiry: dict[str, str] = {}
    expiry_days: dict[str, list[str]] = {}
    for d_str in trading_days:
        d_obj = date.fromisoformat(d_str)
        cands = [e for e in all_exps if 2 <= (date.fromisoformat(e) - d_obj).days <= 14]
        if not cands:
            raise RuntimeError(f"No suitable expiry for {d_str}")
        chosen = cands[0]
        day_to_expiry[d_str] = chosen
        expiry_days.setdefault(chosen, []).append(d_str)

    print(f"    Expiries mapped across {len(trading_days)} days: {len(expiry_days)}", flush=True)
    for e_str, dlist in sorted(expiry_days.items()):
        tag = "EXPIRED" if e_str in expired_set else "ACTIVE"
        print(f"      {e_str} ({tag}): {dlist[0]}..{dlist[-1]} ({len(dlist)} days)", flush=True)

    opt_dir = CACHE_DIR / "options"
    opt_dir.mkdir(parents=True, exist_ok=True)

    # Build list of option contracts to download per expiry
    contracts_meta: dict[str, list[dict]] = {}
    download_jobs: list[tuple[str, dict, str, str, bool]] = []

    for e_str, dlist in sorted(expiry_days.items()):
        min_spot = min(day_high_low[d][0] for d in dlist)
        max_spot = max(day_high_low[d][1] for d in dlist)
        # +/- 550 pts around spot range covers delta 0.25..0.80 and +/-500 PCR strikes
        low_k = int(math.floor((min_spot - 550.0) / 50.0) * 50)
        high_k = int(math.ceil((max_spot + 550.0) / 50.0) * 50)
        # Include 1 extra prior calendar day so prior-close IV fitting works at 09:15
        from_d = (date.fromisoformat(dlist[0]) - timedelta(days=4)).isoformat()
        to_d = dlist[-1]
        is_expired = e_str in expired_set

        if is_expired:
            url = (
                f"https://api.upstox.com/v2/expired-instruments/option/contract"
                f"?instrument_key={urllib.parse.quote(INDEX_KEY, safe='')}&expiry_date={e_str}"
            )
            c_list = (_get_json(session, url, headers).get("data") or [])
        else:
            c_list = [x for x in active_contracts_all if x.get("expiry") == e_str]

        filtered = []
        for x in c_list:
            k = float(x.get("strike_price", 0))
            if low_k <= k <= high_k and x.get("instrument_type") in ("CE", "PE"):
                meta_item = {
                    "instrument_key": x["instrument_key"],
                    "trading_symbol": x.get("trading_symbol", ""),
                    "strike": k,
                    "kind": x["instrument_type"],
                    "expiry": e_str,
                    "lot": int(x.get("lot_size", 65)),
                    "is_expired": is_expired,
                }
                filtered.append(meta_item)
                download_jobs.append((e_str, meta_item, from_d, to_d, is_expired))
        contracts_meta[e_str] = filtered

    save_gz_json(
        CACHE_DIR / "manifest.json.gz",
        {
            "start_date": START_DATE,
            "end_date": END_DATE,
            "trading_days": trading_days,
            "day_to_expiry": day_to_expiry,
            "expiry_days": expiry_days,
            "contracts_meta": contracts_meta,
        },
    )

    print(f"[4/4] Fetching 1m OHLC+Vol+OI candles for {len(download_jobs)} option contracts...", flush=True)

    def fetch_opt(job: tuple[str, dict, str, str, bool]) -> tuple[str, int]:
        e_str, m, from_d, to_d, is_expired = job
        safe_id = f"{e_str}_{int(m['strike'])}_{m['kind']}"
        out = opt_dir / f"{safe_id}.json.gz"
        if out.exists():
            return safe_id, len(load_gz_json(out))
        local_sess = requests.Session()
        enc = urllib.parse.quote(m["instrument_key"], safe="")
        by_ts: dict[str, list] = {}
        if is_expired:
            url = f"https://api.upstox.com/v2/expired-instruments/historical-candle/{enc}/1minute/{to_d}/{from_d}"
            data = _get_json(local_sess, url, headers)
            for r in (data.get("data") or {}).get("candles") or []:
                by_ts[r[0]] = r
        else:
            hist_to = min(to_d, HIST_END)
            if from_d <= hist_to:
                url = f"https://api.upstox.com/v3/historical-candle/{enc}/minutes/1/{hist_to}/{from_d}"
                data = _get_json(local_sess, url, headers)
                for r in (data.get("data") or {}).get("candles") or []:
                    by_ts[r[0]] = r
            if to_d >= END_DATE:
                url2 = f"https://api.upstox.com/v3/historical-candle/intraday/{enc}/minutes/1"
                data2 = _get_json(local_sess, url2, headers)
                for r in (data2.get("data") or {}).get("candles") or []:
                    by_ts[r[0]] = r
        rows = [by_ts[k] for k in sorted(by_ts.keys())]
        save_gz_json(out, rows)
        return safe_id, len(rows)

    done_o = 0
    non_empty = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_opt, j) for j in download_jobs]
        for fut in as_completed(futs):
            sid, cnt = fut.result()
            done_o += 1
            if cnt > 0:
                non_empty += 1
            if done_o % 50 == 0 or done_o == len(download_jobs):
                print(
                    f"    Options fetched: {done_o}/{len(download_jobs)} "
                    f"(non-empty={non_empty}, elapsed={time.time()-t0:.1f}s)",
                    flush=True,
                )

    print(f"DONE! Cached 100% real Upstox market data in {time.time()-t0:.1f}s -> {CACHE_DIR}", flush=True)


if __name__ == "__main__":
    main()
