#!/usr/bin/env python3
"""21-Trader Everyone-vs-Everyone Round-Robin Championship Engine.

Competitors:
  - 20 qualifying trading bots (all strictly beating Winner 51 in Net Profit on Rs 50,000)
  - Member #21: Winner of 51 (A19 [g] — Chennai_WideRunner_32 [g])

Total unique head-to-head matchups: C(21, 2) = 210 matches (20 matches per trader).
Scoring per matchup (6 sub-points across 5 objective criteria):
  1. Total Net Profit (Rs) across Sep 1 - Nov 18, 2026      : 2 sub-points
  2. Daily Head-to-Head Wins across all 54 NSE sessions    : 1 sub-point
  3. Weekly Head-to-Head Wins across all 12 trading weeks  : 1 sub-point
  4. Return / Max-Drawdown (Calmar Ratio)                  : 1 sub-point
  5. Trade Quality (Profit Factor)                         : 1 sub-point
Match Result: Win = 3 pts | Draw = 1 pt | Loss = 0 pts (max 60 pts for 20-0-0).
"""
from __future__ import annotations

from collections import defaultdict
import csv
from datetime import date
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent


def compute_weekly_pnl(daily_rows: List[dict]) -> Dict[str, float]:
    wk: Dict[str, float] = defaultdict(float)
    for r in daily_rows:
        d = date.fromisoformat(r["date"])
        iso_y, iso_w, _ = d.isocalendar()
        wk[f"{iso_y}-W{iso_w:02d}"] += float(r["net_pnl"])
    return {k: round(v, 2) for k, v in sorted(wk.items())}


def compute_monthly_pnl(daily_rows: List[dict]) -> Dict[str, float]:
    mo: Dict[str, float] = defaultdict(float)
    for r in daily_rows:
        mo[r["date"][:7]] += float(r["net_pnl"])
    return {k: round(v, 2) for k, v in sorted(mo.items())}


def compute_sharpe(daily_rows: List[dict]) -> float:
    rets = []
    for r in daily_rows:
        se = float(r["start_equity"])
        if se > 0:
            rets.append(float(r["net_pnl"]) / se)
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / len(rets))
    return round((m / sd) * math.sqrt(252.0), 3) if sd > 1e-9 else 0.0


def score_head_to_head(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Play one head-to-head match between Trader A and Trader B."""
    a_sub = 0.0
    b_sub = 0.0

    # Criterion 1: Total Net Profit (2 sub-points)
    if a["net_pnl"] > b["net_pnl"] + 1e-6:
        a_sub += 2.0
    elif b["net_pnl"] > a["net_pnl"] + 1e-6:
        b_sub += 2.0
    else:
        a_sub += 1.0
        b_sub += 1.0

    # Criterion 2: Daily Head-to-Head wins across all 54 sessions (1 sub-point)
    a_days = {r["date"]: float(r["net_pnl"]) for r in a["daily_rows"]}
    b_days = {r["date"]: float(r["net_pnl"]) for r in b["daily_rows"]}
    common_days = sorted(set(a_days) & set(b_days))
    a_day_w = sum(1 for d in common_days if a_days[d] > b_days[d] + 1e-6)
    b_day_w = sum(1 for d in common_days if b_days[d] > a_days[d] + 1e-6)
    if a_day_w > b_day_w:
        a_sub += 1.0
    elif b_day_w > a_day_w:
        b_sub += 1.0
    else:
        a_sub += 0.5
        b_sub += 0.5

    # Criterion 3: Weekly Head-to-Head wins across all 12 trading weeks (1 sub-point)
    a_wk = a["weekly_pnl"]
    b_wk = b["weekly_pnl"]
    common_wks = sorted(set(a_wk) & set(b_wk))
    a_wk_w = sum(1 for w in common_wks if a_wk[w] > b_wk[w] + 1e-6)
    b_wk_w = sum(1 for w in common_wks if b_wk[w] > a_wk[w] + 1e-6)
    if a_wk_w > b_wk_w:
        a_sub += 1.0
    elif b_wk_w > a_wk_w:
        b_sub += 1.0
    else:
        a_sub += 0.5
        b_sub += 0.5

    # Criterion 4: Calmar / Return-over-MaxDD ratio (1 sub-point)
    a_cal = a["calmar"]
    b_cal = b["calmar"]
    if a_cal > b_cal + 1e-6:
        a_sub += 1.0
    elif b_cal > a_cal + 1e-6:
        b_sub += 1.0
    else:
        a_sub += 0.5
        b_sub += 0.5

    # Criterion 5: Profit Factor (1 sub-point)
    if a["profit_factor"] > b["profit_factor"] + 1e-6:
        a_sub += 1.0
    elif b["profit_factor"] > a["profit_factor"] + 1e-6:
        b_sub += 1.0
    else:
        a_sub += 0.5
        b_sub += 0.5

    if a_sub > b_sub:
        outcome = "W"
        pts_a, pts_b = 3, 0
    elif b_sub > a_sub:
        outcome = "L"
        pts_a, pts_b = 0, 3
    else:
        outcome = "D"
        pts_a, pts_b = 1, 1

    return dict(
        a_id=a["bot_id"],
        b_id=b["bot_id"],
        a_sub=a_sub,
        b_sub=b_sub,
        a_day_wins=a_day_w,
        b_day_wins=b_day_w,
        a_wk_wins=a_wk_w,
        b_wk_wins=b_wk_w,
        outcome_a=outcome,
        pts_a=pts_a,
        pts_b=pts_b,
    )


def main() -> None:
    qual_20 = json.loads((ROOT / "qualified_20_manifest.json").read_text(encoding="utf-8"))
    w51 = json.loads((ROOT / "winner_51_baseline.json").read_text(encoding="utf-8"))

    if len(qual_20) != 20:
        raise RuntimeError(f"Expected exactly 20 qualifying bots, found {len(qual_20)}")

    # Member #21: Winner 51
    w51_entry = {
        "bot_id": "member_21_winner_51",
        "bot_name": "Winner of 51 (A19 [g] — Chennai_WideRunner_32)",
        "family": "Baseline Champion (Member #21)",
        "slug": "winner_51",
        "file": "winner_51/winner_51_bot.py",
        "net_pnl": w51["net_pnl"],
        "return_pct": w51["return_pct"],
        "closed_trades": w51["closed_trades"],
        "wins": w51["wins"],
        "losses": w51["losses"],
        "win_rate_pct": w51["win_rate_pct"],
        "profit_factor": w51["profit_factor"],
        "max_drawdown": w51["max_drawdown"],
        "active_days": w51["active_days"],
        "observed_days": w51["observed_days"],
        "daily_coverage_pct": w51["daily_coverage_pct"],
        "avg_trades_per_day": w51["avg_trades_per_day"],
        "daily_rows": w51["daily_rows"],
    }

    competitors = list(qual_20) + [w51_entry]
    for idx, c in enumerate(competitors, 1):
        c["member_no"] = idx
        c["weekly_pnl"] = compute_weekly_pnl(c["daily_rows"])
        c["monthly_pnl"] = compute_monthly_pnl(c["daily_rows"])
        c["calmar"] = round(c["net_pnl"] / max(1.0, c["max_drawdown"]), 3)
        c["sharpe"] = compute_sharpe(c["daily_rows"])
        c["points"] = 0
        c["match_wins"] = 0
        c["match_draws"] = 0
        c["match_losses"] = 0
        c["total_sub_pts"] = 0.0
        c["total_daily_h2h_wins"] = 0
        c["total_daily_h2h_losses"] = 0

    n = len(competitors)
    matrix: Dict[str, Dict[str, str]] = {c["bot_id"]: {} for c in competitors}
    matchups: List[dict] = []

    for i in range(n):
        matrix[competitors[i]["bot_id"]][competitors[i]["bot_id"]] = "-"
        for j in range(i + 1, n):
            a, b = competitors[i], competitors[j]
            m = score_head_to_head(a, b)
            matchups.append(m)

            a["points"] += m["pts_a"]
            b["points"] += m["pts_b"]
            a["total_sub_pts"] += m["a_sub"]
            b["total_sub_pts"] += m["b_sub"]
            a["total_daily_h2h_wins"] += m["a_day_wins"]
            a["total_daily_h2h_losses"] += m["b_day_wins"]
            b["total_daily_h2h_wins"] += m["b_day_wins"]
            b["total_daily_h2h_losses"] += m["a_day_wins"]

            if m["outcome_a"] == "W":
                a["match_wins"] += 1
                b["match_losses"] += 1
                matrix[a["bot_id"]][b["bot_id"]] = f"W({m['a_sub']:.1f}-{m['b_sub']:.1f})"
                matrix[b["bot_id"]][a["bot_id"]] = f"L({m['b_sub']:.1f}-{m['a_sub']:.1f})"
            elif m["outcome_a"] == "L":
                b["match_wins"] += 1
                a["match_losses"] += 1
                matrix[a["bot_id"]][b["bot_id"]] = f"L({m['a_sub']:.1f}-{m['b_sub']:.1f})"
                matrix[b["bot_id"]][a["bot_id"]] = f"W({m['b_sub']:.1f}-{m['a_sub']:.1f})"
            else:
                a["match_draws"] += 1
                b["match_draws"] += 1
                matrix[a["bot_id"]][b["bot_id"]] = f"D({m['a_sub']:.1f}-{m['b_sub']:.1f})"
                matrix[b["bot_id"]][a["bot_id"]] = f"D({m['b_sub']:.1f}-{m['a_sub']:.1f})"

    # Final championship ranking: Points -> Sub-Points -> Net Profit -> Profit Factor -> Calmar
    standings = sorted(
        competitors,
        key=lambda c: (c["points"], c["total_sub_pts"], c["net_pnl"], c["profit_factor"], c["calmar"]),
        reverse=True,
    )
    for rk, c in enumerate(standings, 1):
        c["final_rank"] = rk

    # Print standings table
    print("=" * 145)
    print("  21-TRADER EVERYONE-VS-EVERYONE ROUND-ROBIN CHAMPIONSHIP (210 PAIRWISE MATCHUPS | SEP 1 - NOV 18, 2026 | Rs 50,000 WALLET)")
    print("=" * 145)
    print(
        f"{'Rk':>2} | {'Bot Name':<36} | {'Pts':>3} | {'W-D-L':<7} | {'Net PnL (Rs)':>12} | {'Ret%':>7} | "
        f"{'Sep PnL':>9} | {'Oct PnL':>9} | {'Nov PnL':>9} | {'PF':>5} | {'Calmar':>6} | {'MaxDD':>9} | {'Tr':>3} | {'ActD':>5}"
    )
    print("-" * 145)
    for c in standings:
        mo = c["monthly_pnl"]
        wdl = f"{c['match_wins']}-{c['match_draws']}-{c['match_losses']}"
        print(
            f"{c['final_rank']:2d} | {c['bot_name'][:36]:<36} | {c['points']:3d} | {wdl:<7} | "
            f"{c['net_pnl']:+12,.2f} | {c['return_pct']:+6.2f}% | "
            f"{mo.get('2026-09', 0.0):+9,.0f} | {mo.get('2026-10', 0.0):+9,.0f} | {mo.get('2026-11', 0.0):+9,.0f} | "
            f"{c['profit_factor']:5.2f} | {c['calmar']:6.2f} | {c['max_drawdown']:9,.2f} | "
            f"{c['closed_trades']:3d} | {c['active_days']:2d}/{c['observed_days']:<2d}"
        )
    print("=" * 145)

    champ = standings[0]
    w51_rk = next(c for c in standings if c["slug"] == "winner_51")
    print(
        f"\nCHAMPION: #{champ['final_rank']} {champ['bot_name']} ({champ['file']})\n"
        f"  Record      : {champ['match_wins']}-{champ['match_draws']}-{champ['match_losses']} ({champ['points']}/60 pts)\n"
        f"  Net Profit  : Rs {champ['net_pnl']:+,.2f} ({champ['return_pct']:+.2f}%) vs Winner 51 Rs {w51_rk['net_pnl']:+,.2f} "
        f"(+{champ['net_pnl']-w51_rk['net_pnl']:,.2f} edge)\n"
        f"  Risk/Quality: PF={champ['profit_factor']:.3f} | Calmar={champ['calmar']:.3f} | Sharpe={champ['sharpe']:.2f} | "
        f"MaxDD=Rs {champ['max_drawdown']:,.2f} | Active Days={champ['active_days']}/{champ['observed_days']} ({champ['avg_trades_per_day']:.2f} tr/day)\n"
        f"  Winner 51   : Finished Rank #{w51_rk['final_rank']}/21 ({w51_rk['match_wins']}-{w51_rk['match_draws']}-{w51_rk['match_losses']}, {w51_rk['points']}/60 pts)"
    )

    # Save CSVs & JSON
    csv_fields = [
        "final_rank", "member_no", "bot_id", "bot_name", "family", "file",
        "points", "match_wins", "match_draws", "match_losses", "total_sub_pts",
        "net_pnl", "return_pct", "sep_pnl", "oct_pnl", "nov_pnl",
        "closed_trades", "wins", "losses", "win_rate_pct", "profit_factor",
        "max_drawdown", "calmar", "sharpe", "active_days", "observed_days",
        "daily_coverage_pct", "avg_trades_per_day",
    ]
    with (ROOT / "tournament_standings.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields)
        w.writeheader()
        for c in standings:
            mo = c["monthly_pnl"]
            row = {k: c.get(k, "") for k in csv_fields}
            row["sep_pnl"] = mo.get("2026-09", 0.0)
            row["oct_pnl"] = mo.get("2026-10", 0.0)
            row["nov_pnl"] = mo.get("2026-11", 0.0)
            w.writerow(row)

    ordered_ids = [c["bot_id"] for c in standings]
    with (ROOT / "pairwise_matrix.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bot_id"] + ordered_ids)
        for bid in ordered_ids:
            w.writerow([bid] + [matrix[bid][cid] for cid in ordered_ids])

    payload = {
        "window": ["2026-09-01", "2026-11-18"],
        "sessions": 54,
        "initial_wallet": 50000.0,
        "total_competitors": len(standings),
        "total_unique_matchups": len(matchups),
        "champion": {k: v for k, v in champ.items() if k != "daily_rows"},
        "winner_51_result": {k: v for k, v in w51_rk.items() if k != "daily_rows"},
        "standings": [{k: v for k, v in c.items() if k != "daily_rows"} for c in standings],
        "pairwise_matrix": matrix,
        "matchups": matchups,
    }
    (ROOT / "tournament_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Generate COMPETITION_REPORT.md
    lines = [
        "# 21-Trader Everyone-vs-Everyone Live Trading Bot Championship",
        "",
        f"- **Dataset:** 100% Real Upstox 1-Minute Market Data (`2026-09-01` to `2026-11-18`, **54 NSE Trading Sessions** — NIFTY 50, India VIX, all 50 NIFTY constituents, and 912 real expired/active weekly NIFTY option contracts)",
        f"- **Starting Wallet:** `₹50,000.00` (Identical capital floor `₹30,000` + `₹2,000` safety buffer, `₹40/side` fees, `0.2%` slippage/side, two-step strictly causal signal→fill execution)",
        f"- **Qualification Threshold:** Strictly beat **Winner 51** (`₹{w51_rk['net_pnl']:+,.2f}`, `+{w51_rk['return_pct']:.2f}%`) in Net Profit with `>= 1.0` avg trades/day",
        f"- **Competition Format:** 20 Qualifying Challengers + Member #21 (`Winner 51`) = **21 Competitors**, **210 Unique Pairwise Head-to-Head Matchups** (`3` pts Win / `1` pt Draw / `0` pts Loss, max `60` pts)",
        "",
        "## Champion of Champions",
        "",
        f"### #{champ['final_rank']} — `{champ['bot_name']}` (`test/bots/{champ['file']}`)",
        f"- **Round-Robin Record:** `{champ['match_wins']}-{champ['match_draws']}-{champ['match_losses']}` (**{champ['points']} / 60 pts**, Sub-Points `{champ['total_sub_pts']:.1f}/120`)",
        f"- **Net Profit (₹50,000 Wallet):** **`₹{champ['net_pnl']:+,.2f}` (`{champ['return_pct']:+.2f}%`)** — beats Winner 51 by **`₹{champ['net_pnl']-w51_rk['net_pnl']:+,.2f}`**",
        f"- **Monthly Breakdown:** Sep `₹{champ['monthly_pnl'].get('2026-09', 0):+,.2f}` | Oct `₹{champ['monthly_pnl'].get('2026-10', 0):+,.2f}` | Nov `₹{champ['monthly_pnl'].get('2026-11', 0):+,.2f}`",
        f"- **Trade Metrics:** `{champ['closed_trades']}` trades (`{champ['wins']}W / {champ['losses']}L`, WR `{champ['win_rate_pct']:.1f}%`), Profit Factor `{champ['profit_factor']:.3f}`, Max Drawdown `₹{champ['max_drawdown']:,.2f}`, Calmar `{champ['calmar']:.3f}`, Sharpe `{champ['sharpe']:.2f}`",
        f"- **Daily Activity:** Active on `{champ['active_days']}/{champ['observed_days']}` sessions (`{champ['daily_coverage_pct']:.1f}%`, `{champ['avg_trades_per_day']:.2f}` trades/day)",
        "",
        "## Full 21-Trader Championship Standings",
        "",
        "| Rank | Bot Name | Family | File | Pts | W-D-L | Net Profit (₹) | Ret% | Sep (₹) | Oct (₹) | Nov (₹) | PF | Calmar | Max DD (₹) | Trades | Active Days |",
        "|---:|---|---|---|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for c in standings:
        mo = c["monthly_pnl"]
        lines.append(
            f"| {c['final_rank']} | **{c['bot_name']}** | {c['family']} | `{c['file']}` | **{c['points']}** | "
            f"{c['match_wins']}-{c['match_draws']}-{c['match_losses']} | ₹{c['net_pnl']:+,.2f} | {c['return_pct']:+.2f}% | "
            f"₹{mo.get('2026-09', 0):+,.0f} | ₹{mo.get('2026-10', 0):+,.0f} | ₹{mo.get('2026-11', 0):+,.0f} | "
            f"{c['profit_factor']:.2f} | {c['calmar']:.2f} | ₹{c['max_drawdown']:,.2f} | {c['closed_trades']} | "
            f"{c['active_days']}/{c['observed_days']} ({c['avg_trades_per_day']:.2f}/d) |"
        )
    lines.append("")
    (ROOT / "COMPETITION_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSaved tournament reports -> {ROOT / 'COMPETITION_REPORT.md'}")


if __name__ == "__main__":
    main()
