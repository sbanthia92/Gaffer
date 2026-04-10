#!/usr/bin/env bash
# Set up scheduled ETL and ingestion cron jobs for The Gaffer on EC2.
# Run as ec2-user after setup_postgres.sh and the first ETL run.
#
#   bash scripts/setup_cron.sh
#
# Jobs installed:
#   Hourly         — etl_v2 snapshot   (live player stats refresh)
#   Tue 03:00 UTC  — etl_v2 gw         (post-gameweek deep sync)
#   07:00 & 19:00  — ingest_press      (news & press conference RAG)
#   00:00 daily    — ingest_fpl        (historical Pinecone refresh)
#
# Historical backfill (one-time, run manually — one season per day):
#   .venv/bin/python -m pipeline.etl_v2 --mode=backfill --season=2024
#   .venv/bin/python -m pipeline.etl_v2 --mode=backfill --season=2023
#   .venv/bin/python -m pipeline.etl_v2 --mode=backfill --season=2022
set -euo pipefail

APP_DIR="/home/ec2-user/gaffer"
PYTHON="$APP_DIR/.venv/bin/python"
LOG_DIR="/var/log/gaffer"

echo "==> Creating log directory..."
sudo mkdir -p "$LOG_DIR"
sudo chown ec2-user:ec2-user "$LOG_DIR"

# ---------------------------------------------------------------------------
# Build the crontab
# ---------------------------------------------------------------------------
CRONTAB=$(crontab -l 2>/dev/null || true)

add_job() {
    local schedule="$1"
    local cmd="$2"
    local comment="$3"
    local full_line="$schedule $cmd # $comment"
    if echo "$CRONTAB" | grep -qF "$cmd"; then
        echo "  already present: $comment"
    else
        CRONTAB="${CRONTAB}"$'\n'"$full_line"
        echo "  added: $comment"
    fi
}

echo "==> Configuring cron jobs..."

# Snapshot — every hour at :05 to avoid thundering herd at :00
add_job \
    "5 * * * *" \
    "cd $APP_DIR && $PYTHON -m pipeline.etl_v2 --mode=snapshot >> $LOG_DIR/etl_snapshot.log 2>&1" \
    "gaffer etl snapshot (hourly)"

# GW sync — Tuesday 03:00 UTC (Mon night fixtures settled, Tue deadlines ahead)
add_job \
    "0 3 * * 2" \
    "cd $APP_DIR && $PYTHON -m pipeline.etl_v2 --mode=gw >> $LOG_DIR/etl_gw.log 2>&1" \
    "gaffer etl gw (weekly)"

# Press & news ingestion — 07:00 and 19:00 UTC
add_job \
    "0 7,19 * * *" \
    "cd $APP_DIR && $PYTHON -m pipeline.ingest_press >> $LOG_DIR/ingest_press.log 2>&1" \
    "gaffer press ingestion (twice daily)"

# Historical FPL ingestion — midnight UTC (player season history + vs-opponent docs)
add_job \
    "0 0 * * *" \
    "cd $APP_DIR && $PYTHON -m pipeline.ingest_fpl >> $LOG_DIR/ingest_fpl.log 2>&1" \
    "gaffer fpl ingestion (daily)"

echo "$CRONTAB" | crontab -

echo ""
echo "================================================================"
echo " Cron jobs installed. Verify with: crontab -l"
echo ""
echo " Logs:"
echo "   $LOG_DIR/etl_snapshot.log   — hourly stats sync"
echo "   $LOG_DIR/etl_gw.log          — weekly GW sync"
echo "   $LOG_DIR/ingest_press.log    — news/press RAG"
echo "   $LOG_DIR/ingest_fpl.log      — historical Pinecone"
echo ""
echo " One-time historical backfill (run one per day):"
echo "   cd $APP_DIR"
echo "   $PYTHON -m pipeline.etl_v2 --mode=backfill --season=2024"
echo "   $PYTHON -m pipeline.etl_v2 --mode=backfill --season=2023"
echo "   $PYTHON -m pipeline.etl_v2 --mode=backfill --season=2022"
echo "================================================================"
