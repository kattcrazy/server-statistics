#!/bin/sh
set -e

# Start Glances in background (web server mode)
glances -w &

# Run monitor.py in foreground
cd /opt/monitoring/scripts
exec python3 monitor.py
