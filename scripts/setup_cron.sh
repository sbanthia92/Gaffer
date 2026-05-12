#!/usr/bin/env bash
# Set up scheduled ETL and ingestion cron jobs for The Gaffer on EC2.
# Run as ec2-user after setup_postgres.sh and the first ETL run.
#
#   bash scripts/setup_cron.sh
#
# Jobs installed:
#   :05 every hour — etl_v2 snapshot        (live player stats refresh)
#   :00 every hour — check_gw_complete      (triggers gw ETL when a GW finishes)
#   07:00 & 19:00  — ingest_press           (news & press conference RAG)
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
    "cd $APP_DIR && ENVIRONMENT=production $PYTHON -m pipeline.etl_v2 --mode=snapshot >> $LOG_DIR/etl_snapshot.log 2>&1" \
    "gaffer etl snapshot (hourly)"

# GW completion check — every hour at :00; triggers ETL --mode=gw only when a new
# gameweek finishes. Replaces the old Tuesday-only cron which missed double-GW
# fixtures falling on other weekdays.
add_job \
    "0 * * * *" \
    "cd $APP_DIR && ENVIRONMENT=production $PYTHON -m pipeline.check_gw_complete >> $LOG_DIR/etl_gw.log 2>&1" \
    "gaffer etl gw check (hourly)"

# Press & news ingestion — 07:00 and 19:00 UTC (via sports-context-mcp package)
add_job \
    "0 7,19 * * *" \
    "cd $APP_DIR && ENVIRONMENT=production $PYTHON -m pipeline.run_press_ingest >> $LOG_DIR/ingest_press.log 2>&1" \
    "gaffer press ingestion (twice daily)"


echo "$CRONTAB" | crontab -

echo ""
echo "================================================================"
echo " Cron jobs installed. Verify with: crontab -l"
echo ""
echo " Logs:"
echo "   $LOG_DIR/etl_snapshot.log   — hourly stats sync"
echo "   $LOG_DIR/etl_gw.log          — GW completion check + gw ETL (hourly)"
echo "   $LOG_DIR/ingest_press.log    — news/press RAG"
echo ""
echo " One-time historical backfill (run one per day):"
echo "   cd $APP_DIR"
echo "   $PYTHON -m pipeline.etl_v2 --mode=backfill --season=2024"
echo "   $PYTHON -m pipeline.etl_v2 --mode=backfill --season=2023"
echo "   $PYTHON -m pipeline.etl_v2 --mode=backfill --season=2022"
echo "================================================================"
