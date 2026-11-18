# 21-Trader Everyone-vs-Everyone Live Trading Bot Championship

- **Dataset:** 100% Real Upstox 1-Minute Market Data (`2026-09-01` to `2026-11-18`, **54 NSE Trading Sessions** — NIFTY 50, India VIX, all 50 NIFTY constituents, and 912 real expired/active weekly NIFTY option contracts)
- **Starting Wallet:** `₹50,000.00` (Identical capital floor `₹30,000` + `₹2,000` safety buffer, `₹40/side` fees, `0.2%` slippage/side, two-step strictly causal signal→fill execution)
- **Qualification Threshold:** Strictly beat **Winner 51** (`₹+16,888.54`, `+33.78%`) in Net Profit with `>= 1.0` avg trades/day
- **Competition Format:** 20 Qualifying Challengers + Member #21 (`Winner 51`) = **21 Competitors**, **210 Unique Pairwise Head-to-Head Matchups** (`3` pts Win / `1` pt Draw / `0` pts Loss, max `60` pts)

## Champion of Champions

### #1 — `Chandelier Runner Tgt50% Lock Rs2200` (`test/bots/bot_01_chandelier_run_t50_l2200.py`)
- **Round-Robin Record:** `20-0-0` (**60 / 60 pts**, Sub-Points `117.0/120`)
- **Net Profit (₹50,000 Wallet):** **`₹+66,851.51` (`+133.70%`)** — beats Winner 51 by **`₹+49,962.97`**
- **Monthly Breakdown:** Sep `₹+1,758.15` | Oct `₹+44,925.06` | Nov `₹+20,168.29`
- **Trade Metrics:** `95` trades (`63W / 32L`, WR `66.3%`), Profit Factor `2.179`, Max Drawdown `₹14,439.32`, Calmar `4.630`, Sharpe `5.58`
- **Daily Activity:** Active on `51/54` sessions (`94.4%`, `1.76` trades/day)

## Full 21-Trader Championship Standings

| Rank | Bot Name | Family | File | Pts | W-D-L | Net Profit (₹) | Ret% | Sep (₹) | Oct (₹) | Nov (₹) | PF | Calmar | Max DD (₹) | Trades | Active Days |
|---:|---|---|---|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1 | **Chandelier Runner Tgt50% Lock Rs2200** | Chandelier Wide-Target | `bot_01_chandelier_run_t50_l2200.py` | **60** | 20-0-0 | ₹+66,851.51 | +133.70% | ₹+1,758 | ₹+44,925 | ₹+20,168 | 2.18 | 4.63 | ₹14,439.32 | 95 | 51/54 (1.76/d) |
| 2 | **Chandelier Runner Tgt48% Lock Rs2200** | Chandelier Wide-Target | `bot_02_chandelier_run_t48_l2200.py` | **57** | 19-0-1 | ₹+65,560.60 | +131.12% | ₹+1,758 | ₹+43,209 | ₹+20,594 | 2.16 | 4.54 | ₹14,439.32 | 95 | 51/54 (1.76/d) |
| 3 | **Chandelier Runner Tgt46% Lock Rs2200** | Chandelier Wide-Target | `bot_03_chandelier_run_t46_l2200.py` | **54** | 18-0-2 | ₹+65,083.15 | +130.17% | ₹+1,758 | ₹+42,731 | ₹+20,594 | 2.15 | 4.51 | ₹14,439.32 | 95 | 51/54 (1.76/d) |
| 4 | **Chandelier Runner Tgt48% Lock Rs2000** | Chandelier Wide-Target | `bot_07_chandelier_run_t48_l2000.py` | **47** | 15-2-3 | ₹+58,246.11 | +116.49% | ₹+1,758 | ₹+34,026 | ₹+22,462 | 2.13 | 4.69 | ₹12,421.24 | 92 | 51/54 (1.70/d) |
| 5 | **Chandelier Runner Tgt50% Lock Rs2400** | Chandelier Wide-Target | `bot_04_chandelier_run_t50_l2400.py` | **47** | 15-2-3 | ₹+63,630.91 | +127.26% | ₹+1,758 | ₹+43,626 | ₹+18,246 | 1.99 | 4.41 | ₹14,439.32 | 102 | 51/54 (1.89/d) |
| 6 | **Chandelier Runner Tgt50% Lock Rs2600** | Chandelier Wide-Target | `bot_05_chandelier_run_t50_l2600.py` | **47** | 15-2-3 | ₹+63,630.91 | +127.26% | ₹+1,758 | ₹+43,626 | ₹+18,246 | 1.99 | 4.41 | ₹14,439.32 | 102 | 51/54 (1.89/d) |
| 7 | **Chandelier Runner Tgt48% Lock Rs2400** | Chandelier Wide-Target | `bot_06_chandelier_run_t48_l2400.py` | **42** | 14-0-6 | ₹+62,340.00 | +124.68% | ₹+1,758 | ₹+41,910 | ₹+18,672 | 1.97 | 4.32 | ₹14,439.32 | 102 | 51/54 (1.89/d) |
| 8 | **Chandelier Runner Tgt44% Lock Rs1850** | Chandelier Wide-Target | `bot_09_chandelier_run_t44_l1850.py` | **37** | 12-1-7 | ₹+48,148.68 | +96.30% | ₹+1,758 | ₹+29,314 | ₹+17,076 | 1.94 | 3.88 | ₹12,421.24 | 92 | 51/54 (1.70/d) |
| 9 | **Chandelier Runner Tgt52% Lock Rs2800** | Chandelier Wide-Target | `bot_08_chandelier_run_t52_l2800.py` | **35** | 11-2-7 | ₹+56,270.70 | +112.54% | ₹+1,758 | ₹+41,193 | ₹+13,319 | 1.80 | 3.39 | ₹16,609.21 | 104 | 51/54 (1.93/d) |
| 10 | **Chandelier Runner Tgt46% Lock Rs2000** | Chandelier Wide-Target | `bot_10_chandelier_run_t46_l2000.py` | **34** | 11-1-8 | ₹+46,909.66 | +93.82% | ₹+1,758 | ₹+28,075 | ₹+17,076 | 1.91 | 3.78 | ₹12,421.24 | 92 | 51/54 (1.70/d) |
| 11 | **Bollinger-Keltner Lock Rs2100** | Volatility Squeeze Breakout | `bot_11_bb_keltner_lock_2100.py` | **26** | 8-2-10 | ₹+46,014.90 | +92.03% | ₹-4,506 | ₹+46,058 | ₹+4,463 | 1.59 | 2.54 | ₹18,077.60 | 95 | 52/54 (1.76/d) |
| 12 | **Bollinger-Keltner Lock Rs2200** | Volatility Squeeze Breakout | `bot_12_bb_keltner_lock_2200.py` | **26** | 8-2-10 | ₹+46,014.90 | +92.03% | ₹-4,506 | ₹+46,058 | ₹+4,463 | 1.59 | 2.54 | ₹18,077.60 | 95 | 52/54 (1.76/d) |
| 13 | **Bollinger-Keltner Lock Rs2300** | Volatility Squeeze Breakout | `bot_13_bb_keltner_lock_2300.py` | **26** | 8-2-10 | ₹+46,014.90 | +92.03% | ₹-4,506 | ₹+46,058 | ₹+4,463 | 1.59 | 2.54 | ₹18,077.60 | 95 | 52/54 (1.76/d) |
| 14 | **Bollinger-Keltner Lock Rs2400** | Volatility Squeeze Breakout | `bot_14_bb_keltner_lock_2400.py` | **21** | 7-0-13 | ₹+44,857.11 | +89.71% | ₹-4,506 | ₹+44,900 | ₹+4,463 | 1.57 | 2.48 | ₹18,077.60 | 98 | 52/54 (1.81/d) |
| 15 | **Convex Gamma-50 Tuned Lock Rs1850** | Convex Gamma Breakout | `bot_19_gamma50_tuned_l1850.py` | **16** | 5-1-14 | ₹+32,058.79 | +64.12% | ₹-1,712 | ₹+19,253 | ₹+14,517 | 1.74 | 2.75 | ₹11,663.69 | 80 | 47/54 (1.48/d) |
| 16 | **Bollinger-Keltner Lock Rs2500** | Volatility Squeeze Breakout | `bot_15_bb_keltner_lock_2500.py` | **14** | 4-2-14 | ₹+43,673.52 | +87.35% | ₹-4,506 | ₹+43,717 | ₹+4,463 | 1.53 | 2.42 | ₹18,077.60 | 100 | 52/54 (1.85/d) |
| 17 | **Convex Gamma-50 Tuned Lock Rs2400** | Convex Gamma Breakout | `bot_20_gamma50_tuned_l2400.py` | **13** | 4-1-15 | ₹+31,312.06 | +62.62% | ₹-1,712 | ₹+23,981 | ₹+9,043 | 1.62 | 2.64 | ₹11,855.37 | 84 | 47/54 (1.56/d) |
| 18 | **Asymmetric Tight-Stop Lock Rs2300** | Tight-Stop Asymmetric R:R | `bot_16_tight_stop_lock_2300.py` | **5** | 1-2-17 | ₹+35,720.20 | +71.44% | ₹-3,981 | ₹+39,718 | ₹-17 | 1.59 | 1.77 | ₹20,203.85 | 98 | 52/54 (1.81/d) |
| 19 | **Asymmetric Tight-Stop Lock Rs2400** | Tight-Stop Asymmetric R:R | `bot_17_tight_stop_lock_2400.py` | **5** | 1-2-17 | ₹+35,720.20 | +71.44% | ₹-3,981 | ₹+39,718 | ₹-17 | 1.59 | 1.77 | ₹20,203.85 | 98 | 52/54 (1.81/d) |
| 20 | **Asymmetric Tight-Stop Lock Rs2500** | Tight-Stop Asymmetric R:R | `bot_18_tight_stop_lock_2500.py` | **5** | 1-2-17 | ₹+35,720.20 | +71.44% | ₹-3,981 | ₹+39,718 | ₹-17 | 1.59 | 1.77 | ₹20,203.85 | 98 | 52/54 (1.81/d) |
| 21 | **Winner of 51 (A19 [g] — Chennai_WideRunner_32)** | Baseline Champion (Member #21) | `winner_51/winner_51_bot.py` | **0** | 0-0-20 | ₹+16,888.54 | +33.78% | ₹-2,627 | ₹+19,661 | ₹-145 | 1.26 | 0.96 | ₹17,636.06 | 93 | 53/54 (1.72/d) |
