# =============================================================================
# PORTALS NFT MONITOR - SIMPLIFIED CONFIGURATION
# =============================================================================

# =============================================================================
# TELEGRAM BOT SETTINGS
# =============================================================================
# Get bot token from @BotFather on Telegram
BOT_TOKEN = "YOUR BOT TOKEN HERE"  # Replace with your bot token from @BotFather

# =============================================================================
# CHANNEL SETTINGS
# =============================================================================
# Primary channel for notifications
CHANNEL_USERNAME = "@YOUR CHANNEL USERNAME HERE"

# =============================================================================
# PORTALS MARKET API SETTINGS
# =============================================================================
PORTALS_API_URL = "https://portals-market.com/api/market/actions/"
PORTALS_CHANNEL_URL = "https://web.telegram.org/k/#@portals"
PORTALS_MARKET_ACTIVITY_URL = "https://portals-market.com/market-activity"

# =============================================================================
# RATE LIMITING & SECURITY SETTINGS
# =============================================================================
# Message sending delays (to avoid bans)
MESSAGE_DELAY = 3           # seconds between messages (reduced for faster notifications)
BATCH_DELAY = 10            # seconds between batches of messages (reduced)
MAX_MESSAGES_PER_MINUTE = 8   # maximum messages per minute (increased slightly)
MAX_MESSAGES_PER_HOUR = 150   # maximum messages per hour (increased)

# API request settings
CHECK_INTERVAL = 5          # seconds between API checks (much faster for real-time)
REQUEST_TIMEOUT = 15        # seconds for API requests (reduced)
RETRY_ATTEMPTS = 2          # number of retry attempts (reduced for speed)

# Token refresh settings
TOKEN_REFRESH_INTERVAL = 3600  # 60 minutes (increased to avoid frequent refreshes)
TOKEN_MAX_AGE = 7200          # 2 hours maximum token age (increased)

# =============================================================================
# DUPLICATE DETECTION & PRICE TRACKING
# =============================================================================
# Track price changes for the same NFT
TRACK_PRICE_CHANGES = True
PRICE_CHANGE_THRESHOLD = 0.01  # Minimum price difference to consider as new sale (TON)

# How long to remember previous sales (to detect duplicates)
DUPLICATE_MEMORY_HOURS = 24    # 24 hours

# =============================================================================
# MESSAGE FORMATTING SETTINGS
# =============================================================================
# Custom emojis for different price ranges


# Special notifications for high-value sales
HIGH_VALUE_THRESHOLD = 50.0    # TON
ULTRA_VALUE_THRESHOLD = 200.0  # TON

# Pin messages for high-value purchases
PIN_MESSAGE_THRESHOLD = 100.0  # TON - Pin messages for purchases above this amount

# =============================================================================
# BROWSER AUTOMATION SETTINGS
# =============================================================================
BROWSER_HEADLESS = False       # Keep browser visible for debugging
BROWSER_TIMEOUT = 60000        # 60 seconds
BROWSER_USER_DATA_DIR = "browser_data"

# =============================================================================
# LOGGING SETTINGS
# =============================================================================
LOG_LEVEL = "INFO"
LOG_FILE = "nft_monitor.log"
LOG_MAX_SIZE_MB = 10
LOG_BACKUP_COUNT = 5

# =============================================================================
# SAFETY FEATURES
# =============================================================================
# Emergency stop settings
MAX_CONSECUTIVE_FAILURES = 10
EMERGENCY_COOLDOWN = 300      # 5 minutes cooldown on emergency stop

# Monitoring limits
MAX_DAILY_MESSAGES = 2000     # Maximum messages per day
DAILY_RESET_HOUR = 0          # Hour to reset daily counters (0 = midnight)

# =============================================================================
# DEVELOPMENT/DEBUG SETTINGS
# =============================================================================
DEBUG_MODE = False
SAVE_RAW_API_RESPONSES = False
VERBOSE_LOGGING = True
