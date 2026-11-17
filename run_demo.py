"""Standalone 15-second simulated Practice Mode demo for NiftyScalperBot."""

from __future__ import annotations

import csv
import os
import sys
import time
from datetime import date, datetime
from typing import List, Tuple

import bot
import config
from bot import InstrumentSeries, NiftyScalperBot, ORBTracker, OptionContract


def build_60_simulated_ticks() -> List[Tuple[datetime, float, float, float]]:
    """
    Build 60 simulated ticks across 09:15:00 to 09:35:00 IST:
      - Ticks 0..19 (09:15:00–09:19:50): Spot establishes ORB_HIGH=25085.0, ORB_LOW=25010.0
      - Ticks 20..59 (09:20:05–09:35:00): Spot breaks >25085.0 to 25165.0;
        CE climbs 109.8 -> 121.0 (Step-1 SL 106.0) -> 126.0 (Step-2 SL 120.0)
        -> 136.0 (Dynamic SL 130.0) -> 129.5 (Trailing SL Exit).
    Returns list of (timestamp_ist, spot_ltp, ce_ltp, pe_ltp).
    """
    today = datetime.now(bot.IST).date()

    def ts(hh: int, mm: int, ss: int) -> datetime:
        return bot.IST.localize(datetime(today.year, today.month, today.day, hh, mm, ss))

    ticks: List[Tuple[datetime, float, float, float]] = [
        # --- 09:15 to 09:20: Establish ORB_HIGH=25085.0, ORB_LOW=25010.0 (20 ticks) ---
        (ts(9, 15, 5), 25040.0, 104.0, 102.0),
        (ts(9, 15, 20), 25025.0, 105.0, 105.0),
        (ts(9, 15, 35), 25010.0, 105.8, 108.0),   # ORB_LOW = 25010.0
        (ts(9, 15, 50), 25030.0, 105.5, 104.0),
        (ts(9, 16, 5), 25050.0, 106.0, 100.0),
        (ts(9, 16, 20), 25065.0, 107.2, 97.5),
        (ts(9, 16, 35), 25085.0, 107.8, 94.0),    # ORB_HIGH = 25085.0
        (ts(9, 16, 50), 25072.0, 107.5, 95.5),
        (ts(9, 17, 5), 25055.0, 107.0, 98.0),
        (ts(9, 17, 20), 25042.0, 106.2, 101.0),
        (ts(9, 17, 35), 25035.0, 105.6, 102.5),
        (ts(9, 17, 50), 25048.0, 106.0, 100.5),
        (ts(9, 18, 5), 25060.0, 106.8, 98.0),
        (ts(9, 18, 20), 25075.0, 107.6, 95.5),
        (ts(9, 18, 35), 25080.0, 108.4, 94.0),
        (ts(9, 18, 50), 25068.0, 108.2, 95.5),
        (ts(9, 19, 5), 25052.0, 108.0, 97.0),
        (ts(9, 19, 20), 25046.0, 107.4, 98.5),
        (ts(9, 19, 35), 25058.0, 107.0, 99.0),
        (ts(9, 19, 50), 25076.0, 107.3, 96.0),

        # --- 09:20 to 09:35: Breakout, Step-1, Step-2, Dynamic Trail, Exit (40 ticks) ---
        (ts(9, 20, 10), 25084.0, 108.8, 94.0),    # 5-Min ORB locks (25010.0 - 25085.0)
        (ts(9, 21, 5), 25092.0, 109.8, 91.5),     # Entry triggers -> Practice Fill = 110.00, Init SL = 98.00
        (ts(9, 21, 25), 25098.0, 111.5, 89.5),
        (ts(9, 21, 45), 25104.0, 113.2, 87.5),
        (ts(9, 22, 10), 25108.0, 115.0, 85.5),
        (ts(9, 22, 35), 25112.0, 116.8, 83.5),
        (ts(9, 23, 0), 25115.0, 118.2, 82.0),
        (ts(9, 23, 25), 25118.0, 119.5, 80.5),
        (ts(9, 23, 50), 25120.0, 120.4, 79.5),
        (ts(9, 24, 15), 25123.0, 121.0, 78.5),    # Step-1 SL triggers -> SL = 106.00
        (ts(9, 24, 40), 25125.0, 121.8, 77.5),
        (ts(9, 25, 5), 25128.0, 122.6, 76.5),
        (ts(9, 25, 30), 25131.0, 123.4, 75.5),
        (ts(9, 25, 55), 25134.0, 124.2, 74.5),
        (ts(9, 26, 20), 25136.0, 124.9, 73.5),
        (ts(9, 26, 45), 25138.0, 125.5, 72.5),
        (ts(9, 27, 10), 25141.0, 126.0, 71.5),    # Step-2 SL triggers -> SL = 120.00 (+₹650 locked)
        (ts(9, 27, 35), 25143.0, 127.0, 70.5),
        (ts(9, 28, 0), 25145.0, 128.2, 69.5),
        (ts(9, 28, 25), 25147.0, 129.4, 68.5),
        (ts(9, 28, 50), 25149.0, 130.6, 67.5),
        (ts(9, 29, 15), 25151.0, 131.8, 66.5),
        (ts(9, 29, 40), 25153.0, 132.5, 65.5),
        (ts(9, 30, 5), 25155.0, 133.2, 64.5),     # 15-Min Primary ORB locks
        (ts(9, 30, 30), 25157.0, 133.9, 64.0),
        (ts(9, 30, 55), 25159.0, 134.5, 63.5),
        (ts(9, 31, 20), 25161.0, 135.1, 63.0),
        (ts(9, 31, 45), 25163.0, 135.6, 62.5),
        (ts(9, 32, 10), 25165.0, 136.0, 62.0),    # Peak Spot=25165.0, CE=136.0 -> Dynamic SL = 130.00
        (ts(9, 32, 30), 25163.0, 135.4, 62.5),
        (ts(9, 32, 50), 25161.0, 134.6, 63.2),
        (ts(9, 33, 10), 25159.0, 133.5, 64.0),
        (ts(9, 33, 30), 25157.0, 132.4, 64.8),
        (ts(9, 33, 50), 25155.0, 131.2, 65.5),
        (ts(9, 34, 10), 25153.0, 130.3, 66.2),
        (ts(9, 34, 25), 25151.0, 129.5, 67.0),    # Pullback <= 130.00 -> TRAILING_SL exit
        (ts(9, 34, 35), 25151.5, 129.8, 66.8),    # Inside 60s re-entry cooldown
        (ts(9, 34, 44), 25152.0, 130.1, 66.6),
        (ts(9, 34, 52), 25152.5, 130.2, 66.5),
        (ts(9, 35, 0), 25153.0, 130.0, 66.7),
    ]
    assert len(ticks) == 60, f"Expected 60 ticks, got {len(ticks)}"
    return ticks


def main() -> None:
    ticks = build_60_simulated_ticks()
    sim_clock = {"now": ticks[0][0]}

    # Patch bot clock and disable network history backfill for standalone offline Practice demo
    bot.now_ist = lambda: sim_clock["now"]
    bot.fetch_intraday_1m_candles = lambda token, key: []

    # Clean previous demo state/log files so the run starts fresh and prints exact generated row
    state_path = os.path.join(config.BASE_DIR, config.STATE_FILE)
    csv_path = os.path.join(config.BASE_DIR, config.TRADE_LOG_CSV)
    for path in (state_path, csv_path):
        if os.path.exists(path):
            os.remove(path)

    ce_contract = OptionContract(
        instrument_key="NSE_FO|25050CE",
        trading_symbol="NIFTY 17NOV 25050 CE",
        strike_price=25050.0,
        option_type="CE",
        expiry_date=date(2026, 11, 17),
        lot_size=65,
    )
    pe_contract = OptionContract(
        instrument_key="NSE_FO|25050PE",
        trading_symbol="NIFTY 17NOV 25050 PE",
        strike_price=25050.0,
        option_type="PE",
        expiry_date=date(2026, 11, 17),
        lot_size=65,
    )

    scalper = NiftyScalperBot(
        access_token="DEMO_PRACTICE_TOKEN",
        mode="P",
        watched_contracts=[ce_contract, pe_contract],
        all_contracts_by_key={
            ce_contract.instrument_key: ce_contract,
            pe_contract.instrument_key: pe_contract,
        },
    )

    assert isinstance(scalper.spot_series, InstrumentSeries)
    assert isinstance(scalper.orb, ORBTracker)

    print("=" * 88)
    print("  PRACTICE MODE [P] DEMO — 60 SIMULATED TICKS OVER 15 SECONDS (09:15 -> 09:35 IST)")
    print("=" * 88)

    cum_spot_vtt = 0
    cum_ce_vtt = 100000
    cum_pe_vtt = 95000

    for idx, (tick_ts, spot_ltp, ce_ltp, pe_ltp) in enumerate(ticks):
        sim_clock["now"] = tick_ts
        cum_spot_vtt += 100
        cum_ce_vtt += 1500
        cum_pe_vtt += 800

        ws_payload = {
            "feeds": {
                config.SPOT_KEY: {
                    "ff": {"indexFF": {"ltpc": {"ltp": spot_ltp}}}
                },
                ce_contract.instrument_key: {
                    "ff": {
                        "marketFF": {
                            "ltpc": {"ltp": ce_ltp, "ltq": 65},
                            "vtt": str(cum_ce_vtt),
                            "oi": "4250000",
                        }
                    }
                },
                pe_contract.instrument_key: {
                    "ff": {
                        "marketFF": {
                            "ltpc": {"ltp": pe_ltp, "ltq": 65},
                            "vtt": str(cum_pe_vtt),
                            "oi": "3800000",
                        }
                    }
                },
            }
        }
        scalper._on_message(ws_payload)

        # Render live dashboard line once every simulated second (every 4 ticks) and on final tick
        if (idx + 1) % 4 == 0 or idx == len(ticks) - 1:
            scalper._render_dashboard_line()
            if not sys.stdout.isatty():
                sys.stdout.write("\n")
                sys.stdout.flush()

        time.sleep(0.25)

    scalper.shutdown()

    print("\n" + "=" * 88)
    print("  ORB VERIFICATION")
    print("=" * 88)
    print(f"ORB_5M_HIGH={scalper.orb.orb_5m_high:.2f} | ORB_5M_LOW={scalper.orb.orb_5m_low:.2f}")
    print(f"ACTIVE_ORB_HIGH={scalper.orb.orb_high:.2f} | ACTIVE_ORB_LOW={scalper.orb.orb_low:.2f}")

    print("\n" + "=" * 88)
    print("  GENERATED trades_log.csv")
    print("=" * 88)
    with open(csv_path, "r", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
        for row in rows:
            print(",".join(row))


if __name__ == "__main__":
    main()
