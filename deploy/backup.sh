#!/usr/bin/env bash
set -euo pipefail

data_dir=/var/lib/trading-assistant
backup_dir="$data_dir/backups"
database="$data_dir/trading-assistant.sqlite3"
timestamp=$(date +%Y%m%d-%H%M%S)

mkdir -p "$backup_dir"
if [[ -f "$database" ]]; then
  sqlite3 "$database" ".backup '$backup_dir/trading-assistant-$timestamp.sqlite3'"
fi
find "$backup_dir" -type f -name 'trading-assistant-*.sqlite3' -mtime +14 -delete
