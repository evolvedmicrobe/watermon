import os

# --- Auth ---
# Change this password before deploying
APP_PASSWORD = "changeme"
SECRET_KEY = os.environ.get("WATERMON_SECRET_KEY", "dev-secret-key-change-in-production")

# --- Timezone ---
# AquaHawk timestamps are naive local time; Rachio events are UTC epoch ms.
# Both are normalized to this timezone for display and alignment.
LOCAL_TIMEZONE = "America/Los_Angeles"

# --- Data ---
# Rachio device was installed on this date
RACHIO_START_DATE = "2023-07-09"
AQUAHAWK_START_DATE = "2022-01-01"
