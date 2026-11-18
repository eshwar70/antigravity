#!/usr/bin/env python3
"""Fast Qualification Arena: evaluates candidate trading bots against Winner 51 on the exact
Sep 1 - Nov 18, 2026 (54 real NSE sessions, Rs 50,000 wallet) strictly causal Upstox dataset.

Loads fast_stream.pkl ONCE in memory (~3s) and runs each 54-session bot in ~0.25s.
Any candidate with Net Profit > Winner 51 (+Rs 16,888.54) and >= 1.0 avg trades/day (active >= 40/54 days)
qualifies for the 21-trader Everyone-vs-Everyone championship.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import pickle
import sys
import time
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
BOTS_DIR = ROOT.parent / "bots"
FAST_STREAM_PATH = ROOT / "market_cache" / "fast_stream.pkl"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BOTS_DIR))

import bot_runtime
from bot_runtime import BASE_BOT_CONFIG, Blocked, CompetitionBotEngine
from candidate_bots import CANDIDATE_SPECS


def _compile_fn(code_str: str, fn_name: str):
    ns: Dict[str, Any] = {"bot_runtime": bot_runtime}
    exec(code_str, ns)
    return ns[fn_name]


def eval_one_spec(spec: Dict[str, Any], stream: list) -> Dict[str, Any]:
    t0 = time.time()
    slug = spec["slug"]
    sig_fn = _compile_fn(spec["signal_code"], "evaluate_signal")
    ex_fn = _compile_fn(spec["exit_code"], "evaluate_exit")
    cfg = {**BASE_BOT_CONFIG, **spec["config"], "initial_wallet": 50000.0}

    engine = CompetitionBotEngine(
        bot_id=slug,
        bot_name=spec["bot_name"],
        config=cfg,
        signal_fn=sig_fn,
        exit_fn=ex_fn,
        folder=None,
        persist=False,
    )

    blocked = 0
    for day_str, rows in stream:
        for ts_str, now_dt, d_s, clk, vix_v, opts, feat in rows:
            try:
                engine.fast_step(ts_str, now_dt, d_s, clk, vix_v, opts, feat)
            except Blocked:
                blocked += 1

    summ = engine.summary()
    drows = engine.daily_rows()
    by_m: Dict[str, float] = {}
    for r in drows:
        m = r["date"][:7]
        by_m[m] = round(by_m.get(m, 0.0) + r["net_pnl"], 2)

    summ["slug"] = slug
    summ["family"] = spec["family"]
    summ["description"] = spec["description"]
    summ["blocked"] = blocked
    summ["elapsed_s"] = round(time.time() - t0, 2)
    summ["monthly_pnl"] = by_m
    summ["daily_rows"] = drows
    summ["trades"] = engine.s["trades"]
    return summ


def export_standalone_bot(rank_idx: int, spec: Dict[str, Any], metrics: Dict[str, Any]) -> Path:
    """Export a clean, standalone, directly runnable live trading bot file into test/bots/."""
    bot_id = f"bot_{rank_idx:02d}_{spec['slug']}"
    out_path = BOTS_DIR / f"{bot_id}.py"
    cfg_repr = json.dumps({**spec["config"], "initial_wallet": 50000.0}, indent=4)

    src = f'''#!/usr/bin/env python3
"""{spec["bot_name"]} ({bot_id}) — Live Upstox Paper Trading Bot.

Family      : {spec["family"]}
Description : {spec["description"]}
Qualification Benchmark (Sep 1 - Nov 18, 2026 | 54 NSE Sessions | Rs 50,000 Wallet):
  - Net Profit    : Rs {metrics["net_pnl"]:+,.2f} ({metrics["return_pct"]:+.2f}%)
  - Trades / WR   : {metrics["closed_trades"]} ({metrics["wins"]}W/{metrics["losses"]}L, {metrics["win_rate_pct"]:.1f}%)
  - Profit Factor : {metrics["profit_factor"]:.3f} | Max DD: Rs {metrics["max_drawdown"]:,.2f}
  - Active Days   : {metrics["active_days"]}/{metrics["observed_days"]} ({metrics["daily_coverage_pct"]:.1f}%), Avg {metrics["avg_trades_per_day"]:.2f}/day

Usage:
  UPSTOX_ACCESS_TOKEN="<token>" python3 {out_path.name} run --wallet 50000
  python3 {out_path.name} status
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bot_runtime import run_bot_cli

BOT_ID = {bot_id!r}
BOT_NAME = {spec["bot_name"]!r}
FAMILY = {spec["family"]!r}
DESCRIPTION = {spec["description"]!r}

CONFIG = json.loads(\'\'\'{cfg_repr}\'\'\')


{spec["signal_code"].strip()}


{spec["exit_code"].strip()}


if __name__ == "__main__":
    run_bot_cli(BOT_ID, BOT_NAME, DESCRIPTION, CONFIG, evaluate_signal, evaluate_exit)
'''
    out_path.write_text(src, encoding="utf-8")
    out_path.chmod(0o755)
    return out_path


def run_qualification(specs: List[Dict[str, Any]], export_top_20: bool = False) -> List[Dict[str, Any]]:
    baseline = json.loads((ROOT / "winner_51_baseline.json").read_text(encoding="utf-8"))
    w51_pnl = float(baseline["net_pnl"])

    t0 = time.time()
    with FAST_STREAM_PATH.open("rb") as f:
        stream = pickle.load(f)
    t_load = time.time() - t0

    print("=" * 142)
    print(
        f"QUALIFICATION ARENA — Benchmark to Beat: Winner 51 = Rs {w51_pnl:+,.2f} (+{baseline['return_pct']:.2f}%) "
        f"| 54 Sessions | Rs 50,000 Wallet (stream loaded in {t_load:.2f}s)"
    )
    print("=" * 142)

    results: List[Dict[str, Any]] = []
    spec_by_slug = {s["slug"]: s for s in specs}
    for sp in specs:
        results.append(eval_one_spec(sp, stream))

    results.sort(key=lambda r: r["net_pnl"], reverse=True)

    qualified = []
    rejected = []
    print(
        f"{'#':>2} | {'Status':<9} | {'Bot Name':<34} | {'Net PnL':>11} | {'vs W51':>10} | "
        f"{'Sep':>8} | {'Oct':>8} | {'Nov':>8} | {'Tr':>3} | {'WR%':>5} | {'PF':>5} | {'MaxDD':>9} | {'ActD':>5} | {'Tr/D':>4}"
    )
    print("-" * 142)
    for idx, r in enumerate(results, 1):
        beats_profit = r["net_pnl"] > w51_pnl
        good_activity = r["avg_trades_per_day"] >= 1.0 and r["active_days"] >= 40
        is_qual = beats_profit and good_activity
        r["eligible"] = is_qual
        r["delta_vs_w51"] = round(r["net_pnl"] - w51_pnl, 2)
        if is_qual:
            qualified.append(r)
        else:
            rejected.append(r)
        tag = "QUALIFIED" if is_qual else ("LOW_FREQ" if beats_profit else "REJECTED")
        mo = r["monthly_pnl"]
        print(
            f"{idx:2d} | {tag:<9} | {r['bot_name'][:34]:<34} | {r['net_pnl']:+11,.2f} | {r['delta_vs_w51']:+10,.2f} | "
            f"{mo.get('2026-09', 0):+8,.0f} | {mo.get('2026-10', 0):+8,.0f} | {mo.get('2026-11', 0):+8,.0f} | "
            f"{r['closed_trades']:3d} | {r['win_rate_pct']:5.1f} | {r['profit_factor']:5.2f} | {r['max_drawdown']:9,.2f} | "
            f"{r['active_days']:2d}/{r['observed_days']:<2d} | {r['avg_trades_per_day']:4.2f}"
        )

    print("-" * 142)
    print(
        f"Tested: {len(results)} | QUALIFIED (> W51 + >=1 trade/day): {len(qualified)} | "
        f"Rejected: {len(rejected)} | Total Elapsed: {time.time()-t0:.1f}s"
    )

    log_payload = {
        "winner_51_baseline": {k: v for k, v in baseline.items() if k != "daily_rows"},
        "total_tested": len(results),
        "total_qualified": len(qualified),
        "candidates": [
            {k: v for k, v in r.items() if k not in ("daily_rows", "trades")}
            for r in results
        ],
    }
    (ROOT / "qualification_log.json").write_text(json.dumps(log_payload, indent=2), encoding="utf-8")

    if export_top_20 and len(qualified) >= 20:
        selected = qualified[:20]
        for old in BOTS_DIR.glob("bot_[0-9][0-9]_*.py"):
            old.unlink()
        exported_manifest = []
        for rank_i, r in enumerate(selected, 1):
            sp = spec_by_slug[r["slug"]]
            bot_file = export_standalone_bot(rank_i, sp, r)
            bot_id = bot_file.stem
            tdir = ROOT / "bot_trades" / bot_id
            tdir.mkdir(parents=True, exist_ok=True)
            with (tdir / "daily_pnl.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(r["daily_rows"][0].keys()))
                w.writeheader()
                w.writerows(r["daily_rows"])
            tfields = ["key", "kind", "strike", "setup", "entered", "exited", "quantity", "entry", "exit", "net_pnl", "charges", "reason"]
            with (tdir / "trades.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=tfields)
                w.writeheader()
                for t in r["trades"]:
                    w.writerow({k: t.get(k, "") for k in tfields})
            summ_clean = {k: v for k, v in r.items() if k not in ("daily_rows", "trades")}
            summ_clean["bot_id"] = bot_id
            summ_clean["file"] = str(bot_file)
            (tdir / "summary.json").write_text(json.dumps(summ_clean, indent=2), encoding="utf-8")
            exported_manifest.append(
                {
                    "bot_id": bot_id,
                    "bot_name": r["bot_name"],
                    "family": r["family"],
                    "slug": r["slug"],
                    "file": bot_file.name,
                    "net_pnl": r["net_pnl"],
                    "return_pct": r["return_pct"],
                    "closed_trades": r["closed_trades"],
                    "wins": r["wins"],
                    "losses": r["losses"],
                    "win_rate_pct": r["win_rate_pct"],
                    "profit_factor": r["profit_factor"],
                    "max_drawdown": r["max_drawdown"],
                    "active_days": r["active_days"],
                    "observed_days": r["observed_days"],
                    "daily_coverage_pct": r["daily_coverage_pct"],
                    "avg_trades_per_day": r["avg_trades_per_day"],
                    "daily_rows": r["daily_rows"],
                }
            )
        (ROOT / "qualified_20_manifest.json").write_text(json.dumps(exported_manifest, indent=2), encoding="utf-8")
        print(f"\nEXPORTED 20 QUALIFYING BOTS -> {BOTS_DIR}")
    return results


if __name__ == "__main__":
    export_flag = "--export" in sys.argv
    run_qualification(CANDIDATE_SPECS, export_top_20=export_flag)
