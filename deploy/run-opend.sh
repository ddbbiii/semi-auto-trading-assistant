#!/usr/bin/env bash
set -euo pipefail

# Command-line OpenD exits when its interactive stdin reaches EOF. Keep stdin
# open without sending commands; systemd owns and stops the complete pipeline.
tail -f /dev/null | script -qfec \
  "/opt/trading-assistant/opend/FutuOpenD \
    -cfg_file=/opt/trading-assistant/opend/FutuOpenD.xml \
    -api_ip=127.0.0.1 \
    -api_port=11111 \
    -console=1 \
    -no_monitor=1" \
  /dev/null
