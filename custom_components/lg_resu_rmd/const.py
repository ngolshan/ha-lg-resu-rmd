"""Constants for the LG RESU RMD integration."""

DOMAIN = "lg_resu_rmd"

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 300  # seconds
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 3600

DEFAULT_NAME = "LG RESU16H"
MANUFACTURER = "LG Energy Solution"

# One retry after a failed poll, then the entities go unavailable.
RETRY_DELAY = 5  # seconds
