#!/usr/bin/env bash
set -e

PROJECT_DIR="$HOME/dcsm-project"
source "$PROJECT_DIR/venv/bin/activate"

echo "Menghentikan proses storage_server lama (kalau ada)..."
pkill -f "storage_server.py" 2>/dev/null || true
sleep 1

echo "Menjalankan Storage Primary (port 50053)..."
cd "$PROJECT_DIR/storage-primary"
STORAGE_ROLE=primary STORAGE_PORT=50053 DATA_DIR=./data CERT_DIR=./certs REPLICATE_TO=localhost:50054 \
  nohup python3 storage_server.py > "$PROJECT_DIR/primary.log" 2>&1 &
echo "Primary PID: $!"

echo "Menjalankan Storage Backup (port 50054)..."
cd "$PROJECT_DIR/storage-backup"
STORAGE_ROLE=backup STORAGE_PORT=50054 DATA_DIR=./data CERT_DIR=./certs \
  nohup python3 storage_server.py > "$PROJECT_DIR/backup.log" 2>&1 &
echo "Backup PID: $!"

sleep 2
echo ""
echo "=== Status ==="
ss -tlnp 2>/dev/null | grep -E "50053|50054" || sudo ss -tlnp | grep -E "50053|50054"
echo ""
echo "Log Primary: tail -f $PROJECT_DIR/primary.log"
echo "Log Backup:  tail -f $PROJECT_DIR/backup.log"
