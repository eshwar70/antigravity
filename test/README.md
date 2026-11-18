# 🏆 NIFTY 50 Trading Bot Championship (Sep 1 – Nov 18, 2026)

## 📁 Directory Architecture
Per your instructions, the repository is strictly split into two independent folders so it is easy to use the bots later:
```
test/
├── bots/                              # Standalone executable trading bots ready for live practice trading
│   ├── bot_01_chandelier_run_t50_l2200.py   # 🏆 TOURNAMENT CHAMPION (+₹66,851.51 / +133.70% PnL)
│   ├── bot_02_chandelier_run_t48_l2200.py   # Runner-Up (+₹65,560.60 / +131.12% PnL)
│   ├── bot_03_chandelier_run_t46_l2200.py   # 3rd Place (+₹65,083.15 / +130.17% PnL)
│   ├── bot_04_chandelier_run_t50_l2400.py   # 4th Place (+₹63,630.91 / +127.26% PnL)
│   ├── bot_05_chandelier_run_t50_l2600.py   # 5th Place (+₹63,630.91 / +127.26% PnL)
│   ├── bot_06_chandelier_run_t48_l2400.py   # 6th Place (+₹62,340.00 / +124.68% PnL)
│   ├── bot_07_chandelier_run_t48_l2000.py   # 7th Place (+₹58,246.11 / +116.49% PnL)
│   ├── bot_08_chandelier_run_t52_l2800.py   # 8th Place (+₹56,270.70 / +112.54% PnL)
│   ├── bot_09_chandelier_run_t44_l1850.py   # 9th Place (+₹48,148.68 / +96.30% PnL)
│   ├── bot_10_chandelier_run_t46_l2000.py   # 10th Place (+₹46,909.66 / +93.82% PnL)
│   ├── bot_11_bb_keltner_lock_2100.py       # 11th Place (+₹46,014.90 / +92.03% PnL)
│   ├── bot_12_bb_keltner_lock_2200.py       # 12th Place (+₹46,014.90 / +92.03% PnL)
│   ├── bot_13_bb_keltner_lock_2300.py       # 13th Place (+₹46,014.90 / +92.03% PnL)
│   ├── bot_14_bb_keltner_lock_2400.py       # 14th Place (+₹44,857.11 / +89.71% PnL)
│   ├── bot_15_bb_keltner_lock_2500.py       # 15th Place (+₹43,673.52 / +87.35% PnL)
│   ├── bot_16_tight_stop_lock_2300.py       # 16th Place (+₹35,720.20 / +71.44% PnL)
│   ├── bot_17_tight_stop_lock_2400.py       # 17th Place (+₹35,720.20 / +71.44% PnL)
│   ├── bot_18_tight_stop_lock_2500.py       # 18th Place (+₹35,720.20 / +71.44% PnL)
│   ├── bot_19_gamma50_tuned_l1850.py        # 19th Place (+₹32,058.79 / +64.12% PnL)
│   ├── bot_20_gamma50_tuned_l2400.py        # 20th Place (+₹31,312.06 / +62.62% PnL)
│   ├── bot_runtime.py                       # Self-contained live practice engine & technical indicators
│   ├── nifty_membership.json                # Verified NIFTY 50 constituent key mapping
│   └── winner_51/                           # Baseline champion (`A19 [g]` / `Chennai_WideRunner_32`)
│       ├── winner_51_bot.py
│       ├── config_50k.json
│       ├── fast_practice.py
│       └── core.py
│
└── test_data/                         # 100% Real Upstox market data, replay caches & tournament audits
    ├── market_cache/                  # Cached 1m candles (NIFTY 50, VIX, 50 constituents, 912 option contracts)
    │   ├── nifty_1m.json.gz
    │   ├── vix_1m.json.gz
    │   ├── constituents/
    │   ├── options/
    │   └── fast_stream.pkl
    ├── bot_trades/                    # Full per-bot trades.csv and daily_pnl.csv for all 21 traders
    ├── tournament_standings.csv       # Official 21-trader round-robin standings
    ├── pairwise_matrix.csv            # Complete 21x21 head-to-head match outcomes
    ├── tournament_results.json        # Comprehensive tournament JSON dataset
    ├── COMPETITION_REPORT.md          # Multi-page markdown competition analysis
    ├── winner_51_baseline.json        # Exact Winner 51 54-session baseline result
    ├── qualified_20_manifest.json     # The 20 qualified challenger bots metadata
    └── qualification_log.json         # Full audit log of all 69 candidates tested
```

---

## 🚀 How to Run the Bots in Live Practice Trading
Each bot inside `test/bots/` is completely standalone and ready for live paper trading against real-time Upstox market streams:

```bash
# 1. Run the Tournament Champion (Bot 01) live with Rs 50,000 starting wallet:
UPSTOX_ACCESS_TOKEN="<your_token>" python3 test/bots/bot_01_chandelier_run_t50_l2200.py run --wallet 50000

# 2. View bot strategy parameters & risk rules:
python3 test/bots/bot_01_chandelier_run_t50_l2200.py status

# 3. Run any other bot (e.g., Bollinger-Keltner Breakout Bot 11):
UPSTOX_ACCESS_TOKEN="<your_token>" python3 test/bots/bot_11_bb_keltner_lock_2100.py run --wallet 50000

# 4. Run Winner 51 (Member #21):
UPSTOX_ACCESS_TOKEN="<your_token>" python3 test/bots/winner_51/winner_51_bot.py run --wallet 50000
```

---

## 📊 Summary of the 21-Trader Round-Robin Championship

- **Tested Window:** September 1, 2026 to November 18, 2026 (**54 real NSE trading sessions**)
- **Starting Wallet:** ₹50,000.00
- **Execution Rules:** Identical to Winner 51 (`₹30,000` capital floor + `₹2,000` buffer, `₹40/side` fees, `0.2%` slippage, strictly causal 2-step signal→fill execution, real depth & Greeks checks)
- **Qualification Criteria:** Must strictly exceed **Winner 51** (`₹16,888.54` / `+33.78%`) in Net Profit with `>= 1.0` average trades/day across the 54 sessions.
- **Matchup Format:** `C(21, 2) = 210` unique head-to-head matches (`3` pts Win, `1` pt Draw, `0` pts Loss, max `60` pts).

| Rank | Bot Name | File | Match Record | Pts | Net Profit (₹50k) | Return % | Profit Factor | Calmar | Max Drawdown | Trades | Active Days |
|---:|---|---|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 🥇 **1** | **Chandelier Runner Tgt50% Lock Rs2200** | `bot_01_*.py` | **20-0-0** | **60** | **+₹66,851.51** | **+133.70%** | **2.18** | **4.63** | ₹14,439.32 | 95 | 51/54 (1.76/d) |
| 🥈 **2** | **Chandelier Runner Tgt48% Lock Rs2200** | `bot_02_*.py` | **19-0-1** | **57** | **+₹65,560.60** | **+131.12%** | **2.16** | **4.54** | ₹14,439.32 | 95 | 51/54 (1.76/d) |
| 🥉 **3** | **Chandelier Runner Tgt46% Lock Rs2200** | `bot_03_*.py` | **18-0-2** | **54** | **+₹65,083.15** | **+130.17%** | **2.15** | **4.51** | ₹14,439.32 | 95 | 51/54 (1.76/d) |
| 4 | **Chandelier Runner Tgt48% Lock Rs2000** | `bot_04_*.py` | 15-2-3 | 47 | +₹58,246.11 | +116.49% | 2.13 | 4.69 | ₹12,421.24 | 92 | 51/54 (1.70/d) |
| 5 | **Chandelier Runner Tgt50% Lock Rs2400** | `bot_05_*.py` | 15-2-3 | 47 | +₹63,630.91 | +127.26% | 1.99 | 4.41 | ₹14,439.32 | 102 | 51/54 (1.89/d) |
| 6 | **Chandelier Runner Tgt50% Lock Rs2600** | `bot_06_*.py` | 15-2-3 | 47 | +₹63,630.91 | +127.26% | 1.99 | 4.41 | ₹14,439.32 | 102 | 51/54 (1.89/d) |
| 7 | **Chandelier Runner Tgt48% Lock Rs2400** | `bot_07_*.py` | 14-0-6 | 42 | +₹62,340.00 | +124.68% | 1.97 | 4.32 | ₹14,439.32 | 102 | 51/54 (1.89/d) |
| 8 | **Chandelier Runner Tgt44% Lock Rs1850** | `bot_08_*.py` | 12-1-7 | 37 | +₹48,148.68 | +96.30% | 1.94 | 3.88 | ₹12,421.24 | 92 | 51/54 (1.70/d) |
| 9 | **Chandelier Runner Tgt52% Lock Rs2800** | `bot_09_*.py` | 11-2-7 | 35 | +₹56,270.70 | +112.54% | 1.80 | 3.39 | ₹16,609.21 | 104 | 51/54 (1.93/d) |
| 10 | **Chandelier Runner Tgt46% Lock Rs2000** | `bot_10_*.py` | 11-1-8 | 34 | +₹46,909.66 | +93.82% | 1.91 | 3.78 | ₹12,421.24 | 92 | 51/54 (1.70/d) |
| 11 | **Bollinger-Keltner Lock Rs2100** | `bot_11_*.py` | 8-2-10 | 26 | +₹46,014.90 | +92.03% | 1.59 | 2.54 | ₹18,077.60 | 95 | 52/54 (1.76/d) |
| 12 | **Bollinger-Keltner Lock Rs2200** | `bot_12_*.py` | 8-2-10 | 26 | +₹46,014.90 | +92.03% | 1.59 | 2.54 | ₹18,077.60 | 95 | 52/54 (1.76/d) |
| 13 | **Bollinger-Keltner Lock Rs2300** | `bot_13_*.py` | 8-2-10 | 26 | +₹46,014.90 | +92.03% | 1.59 | 2.54 | ₹18,077.60 | 95 | 52/54 (1.76/d) |
| 14 | **Bollinger-Keltner Lock Rs2400** | `bot_14_*.py` | 7-0-13 | 21 | +₹44,857.11 | +89.71% | 1.57 | 2.48 | ₹18,077.60 | 98 | 52/54 (1.81/d) |
| 15 | **Convex Gamma-50 Tuned Lock Rs1850** | `bot_15_*.py` | 5-1-14 | 16 | +₹32,058.79 | +64.12% | 1.74 | 2.75 | ₹11,663.69 | 80 | 47/54 (1.48/d) |
| 16 | **Bollinger-Keltner Lock Rs2500** | `bot_16_*.py` | 4-2-14 | 14 | +₹43,673.52 | +87.35% | 1.53 | 2.42 | ₹18,077.60 | 100 | 52/54 (1.85/d) |
| 17 | **Convex Gamma-50 Tuned Lock Rs2400** | `bot_17_*.py` | 4-1-15 | 13 | +₹31,312.06 | +62.62% | 1.62 | 2.64 | ₹11,855.37 | 84 | 47/54 (1.56/d) |
| 18 | **Asymmetric Tight-Stop Lock Rs2300** | `bot_18_*.py` | 1-2-17 | 5 | +₹35,720.20 | +71.44% | 1.59 | 1.77 | ₹20,203.85 | 98 | 52/54 (1.81/d) |
| 19 | **Asymmetric Tight-Stop Lock Rs2400** | `bot_19_*.py` | 1-2-17 | 5 | +₹35,720.20 | +71.44% | 1.59 | 1.77 | ₹20,203.85 | 98 | 52/54 (1.81/d) |
| 20 | **Asymmetric Tight-Stop Lock Rs2500** | `bot_20_*.py` | 1-2-17 | 5 | +₹35,720.20 | +71.44% | 1.59 | 1.77 | ₹20,203.85 | 98 | 52/54 (1.81/d) |
| 21 | **Winner of 51 (Member #21)** | `winner_51/` | 0-0-20 | 0 | +₹16,888.54 | +33.78% | 1.26 | 0.96 | ₹17,636.06 | 93 | 53/54 (1.72/d) |
