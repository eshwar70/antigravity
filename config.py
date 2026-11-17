"""Configuration constants for the All-Weather Multi-Strategy NIFTY Micro-Scalper."""

import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOTENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(DOTENV_PATH)

# Upstox API Credentials
API_KEY = (os.getenv("API_KEY") or os.getenv("UPSTOX_API_KEY") or "").strip()
API_SECRET = (os.getenv("API_SECRET") or os.getenv("UPSTOX_API_SECRET") or "").strip()
REDIRECT_URI = (
    os.getenv("REDIRECT_URI")
    or os.getenv("UPSTOX_REDIRECT_URI")
    or "http://localhost:5000/callback"
).strip()
ACCESS_TOKEN = (
    os.getenv("ACCESS_TOKEN") or os.getenv("UPSTOX_ACCESS_TOKEN") or ""
).strip()

# Capital & Contract Defaults (Live Trading Base Configuration)
WALLET_CAPITAL = 11000.0
DEFAULT_LOT_SIZE = 65
LOTS_PER_TRADE = 1
PRODUCT_TYPE = "D"  # Delivery (NRML) option buying: avoids 3:15 PM MIS auto-square-off penalty
SPOT_KEY = "NSE_INDEX|Nifty 50"

# Session Timings (IST)
TIMEZONE = "Asia/Kolkata"
MARKET_OPEN = "09:15:00"
INITIAL_ORB_END = "09:20:00"
PRIMARY_ORB_END = "09:30:00"
LAST_NEW_ENTRY_TIME = "15:15:00"
HARD_SQUARE_OFF_TIME = "15:28:00"

# Risk, Trade Cap & Kill-Switch Rules
MAX_DAILY_LOSS_INR = -1500.0
UNLIMITED_TRADES = False
MAX_TRADES_PER_DAY = 10
REENTRY_COOLDOWN_SECS = 120
BROKERAGE_AND_TAX_PER_TRADE = 55.0
FLAT_BROKERAGE_ROUND = 40.0
STATUTORY_TAX_PER_LOT = 15.0
MPP_BUFFER_PTS = 1.5
PRACTICE_SLIPPAGE_PTS = 0.20

# Quick-Hit Micro-Scalp Stop-Loss & Target Ladder
INITIAL_SL_PTS = 5.5
BREAKEVEN_TRIGGER_PTS = 3.2
BREAKEVEN_LOCK_PTS = 1.2
QUICK_LOCK_TRIGGER_PTS = 5.0
QUICK_LOCK_SL_PTS = 4.0
MICRO_TRAIL_TRIGGER_PTS = 6.5
MICRO_TRAIL_GAP_PTS = 1.0
INSTANT_TAKE_PROFIT_PTS = 9.0
FAST_SCRATCH_MINS = 5
FAST_SCRATCH_PROFIT_PTS = 1.0
FAST_SCRATCH_SL_OFFSET = -2.5

# Strategy & Optional Hedging Config
ALLOW_HEDGING = False
HEDGE_WING_OFFSET = 150
MIN_OPTION_PREMIUM = 75.0
MAX_OPTION_PREMIUM = 155.0
ER_TREND_THRESHOLD = 0.38
OVEREXTENSION_MAX_PTS = 4.0

# Order & Instrument Metadata
ALGO_NAME = "NIFTY_MOMENTUM_SCALPER"
ORDER_TAG = "ANTIGRAVITY_ORB"
INSTRUMENT_MASTER_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
)

# File Paths
STATE_FILE = "state.json"
TRADE_LOG_CSV = "trades_log.csv"
INSTRUMENT_CACHE = "nse_instruments.json.gz"
