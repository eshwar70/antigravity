#!/usr/bin/env python3
"""Build an ultra-fast pre-indexed replay stream from arena_days/*.pkl (100% identical causal data)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import pickle
import sys
import time

ROOT = Path(__file__).resolve().parent
ARENA_DIR = ROOT / "market_cache" / "arena_days"
OUT_PATH = ROOT / "market_cache" / "fast_stream.pkl"


def main() -> None:
    t0 = time.time()
    files = sorted(ARENA_DIR.glob("*.pkl"))
    stream = []
    for fp in files:
        day_str = fp.stem
        d_obj = date.fromisoformat(day_str)
        with fp.open("rb") as f:
            items = pickle.load(f)
        day_rows = []
        for snap, feat in items:
            ts_str = snap["timestamp"]
            now_dt = feat["now"]
            clock = feat["clock"]
            vix_val = float((snap.get("vix") or {}).get("value") or 0.0)
            opts_by_key = {}
            for o in snap["options"]:
                o2 = dict(o)
                o2["_dte"] = (date.fromisoformat(o["expiry"]) - d_obj).days
                opts_by_key[o["key"]] = o2
            day_rows.append((ts_str, now_dt, day_str, clock, vix_val, opts_by_key, feat))
        stream.append((day_str, day_rows))

    with OUT_PATH.open("wb") as f:
        pickle.dump(stream, f, protocol=pickle.HIGHEST_PROTOCOL)
    size_mb = OUT_PATH.stat().st_size / (1024 * 1024)
    print(f"Built {OUT_PATH.name} ({len(stream)} days, {size_mb:.1f} MB) in {time.time()-t0:.2f}s", flush=True)


if __name__ == "__main__":
    main()
