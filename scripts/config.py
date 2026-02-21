"""Configuration for server monitoring."""

import os

# MQTT - all configurable via environment variables
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")

# MQTT topic prefix (e.g., "server" -> topics like server/containers/plex/status)
TOPIC_PREFIX = os.environ.get("TOPIC_PREFIX", "server")

# Error log keywords
ERROR_KEYWORDS = [
    "ERROR",
    "CRITICAL",
    "WARN",
    "WARNING",
    "Exception",
    "FATAL",
]

# Kernel/I/O error keywords for dmesg
KERNEL_ERROR_KEYWORDS = [
    "i/o error",
    "I/O error",
    "nvme",
    "NVMe",
    "critical medium error",
    "medium error",
    "blk_update_request",
    "buffer I/O error",
    "DRDY ERR",
    "reset failed",
    "timeout",
]

# Loop interval in seconds (how often to check containers)
LOOP_INTERVAL = int(os.environ.get("LOOP_INTERVAL", "300"))  # default 5 minutes
