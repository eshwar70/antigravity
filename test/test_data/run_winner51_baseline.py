#!/usr/bin/env python3
"""Run unmodified Winner of 51 (A19 [g] — Chennai_WideRunner_32 [g]) on the exact
Sep 1 – Nov 18, 2026 (54 real NSE sessions) ₹50,000 causal benchmark dataset.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
BOTS_DIR = ROOT.parent / "bots"
W51_DIR = BOTS_DIR / "winner_51"
sys.path.insert(0, str(W51_DIR))
sys.path.insert(0, str(ROOT))

from core import Blocked, stamp
from fast_practice import QuickPracticeEngine, load_fast_config
from snapshot_builder import MarketDataset


class FastReplayWinner51(QuickPracticeEngine):
    """Exact unmodified QuickPracticeEngine logic, deferring disk I/O until final reports()."""

    def save(self):
        return

    def log(self, kind, now, **data):
        return


def main() -> None:
    t0 = time.time()
    ds = MarketDataset()
    cfg = load_fast_config(W51_DIR / "config_50k.json")
    cfg["initial_wallet"] = 50000.0

    out_dir = ROOT / "bot_trades" / "winner_51"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Remove any old state file so we start strictly fresh at 50000
    state_p = out_dir / "practice_state.json"
    if state_p.exists():
        state_p.unlink()

    engine = FastReplayWinner51(cfg, out_dir)
    accepted = 0
    blocked = 0
    block_reasons = {}

    for d_idx, day_str in enumerate(ds.trading_days, 1):
        snaps = ds.build_day_snapshots(day_str)
        for snap in snaps:
            try:
                engine.step(snap, stamp(snap["timestamp"]))
                accepted += 1
            except Blocked as exc:
                blocked += 1
                k = str(exc)
                block_reasons[k] = block_reasons.get(k, 0) + 1
        if d_idx % 10 == 0 or d_idx == len(ds.trading_days):
            print(
                f"  [{d_idx:2d}/{len(ds.trading_days)}] {day_str} | "
                f"Equity: Rs {engine.s['equity']:,.2f} | "
                f"Net PnL: Rs {engine.s['equity']-50000.0:+,.2f} | "
                f"Trades: {len(engine.s['trades'])}",
                flush=True,
            )

    summary = engine.reports()
    trades = engine.s["trades"]
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    gw = sum(t["net_pnl"] for t in wins)
    gl = abs(sum(t["net_pnl"] for t in losses))
    pf = (gw / gl) if gl > 0 else (99.0 if gw > 0 else 0.0)

    daily_rows = []
    for day, d in sorted(engine.s["daily"].items()):
        dt = [t for t in trades if stamp(t["exited"]).date().isoformat() == day]
        daily_rows.append(
            dict(
                date=day,
                start_equity=round(d["start_equity"], 2),
                end_equity=round(d["end_equity"], 2),
                net_pnl=round(d["end_equity"] - d["start_equity"], 2),
                closed_trades=len(dt),
                wins=sum(1 for t in dt if t["net_pnl"] > 0),
                losses=sum(1 for t in dt if t["net_pnl"] <= 0),
            )
        )

    active_days = sum(1 for r in daily_rows if r["closed_trades"] >= 1)
    baseline = dict(
        bot_id="winner_51",
        bot_name="Winner of 51 (A19 [g] — Chennai_WideRunner_32 [g])",
        window=[ds.trading_days[0], ds.trading_days[-1]],
        sessions=len(ds.trading_days),
        initial_wallet=50000.0,
        equity=round(engine.s["equity"], 2),
        cash=round(engine.s["cash"], 2),
        net_pnl=round(engine.s["equity"] - 50000.0, 2),
        return_pct=round((engine.s["equity"] - 50000.0) / 50000.0 * 100.0, 2),
        closed_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate_pct=round(len(wins) / len(trades) * 100.0, 2) if trades else 0.0,
        profit_factor=round(pf, 3),
        max_drawdown=round(engine.s["max_drawdown"], 2),
        observed_days=len(daily_rows),
        active_days=active_days,
        daily_coverage_pct=round(active_days / len(daily_rows) * 100.0, 2) if daily_rows else 0.0,
        avg_trades_per_day=round(len(trades) / len(daily_rows), 3) if daily_rows else 0.0,
        accepted_snapshots=accepted,
        blocked_snapshots=blocked,
        block_reasons=block_reasons,
        elapsed_seconds=round(time.time() - t0, 2),
        daily_rows=daily_rows,
    )

    (ROOT / "winner_51_baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print("\n" + "=" * 90)
    print(f"WINNER 51 BASELINE ({ds.trading_days[0]} to {ds.trading_days[-1]}, {len(ds.trading_days)} sessions, Rs 50,000 wallet)")
    print("=" * 90)
    print(
        f"  Ending Equity : Rs {baseline['equity']:,.2f}\n"
        f"  Net Profit    : Rs {baseline['net_pnl']:+,.2f} ({baseline['return_pct']:+.2f}%)\n"
        f"  Closed Trades : {baseline['closed_trades']} ({baseline['wins']}W / {baseline['losses']}L, WR {baseline['win_rate_pct']:.1f}%)\n"
        f"  Profit Factor : {baseline['profit_factor']:.3f}\n"
        f"  Max Drawdown  : Rs {baseline['max_drawdown']:,.2f}\n"
        f"  Active Days   : {baseline['active_days']}/{baseline['observed_days']} ({baseline['daily_coverage_pct']:.1f}%) | Avg {baseline['avg_trades_per_day']:.2f}/day\n"
        f"  Runtime       : {baseline['elapsed_seconds']}s (accepted={accepted}, blocked={blocked})"
    )


if __name__ == "__main__":
    main()
