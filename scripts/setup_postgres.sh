#!/usr/bin/env bash
# One-time PostgreSQL setup for The Gaffer on Amazon Linux 2023.
# Run as ec2-user via SSH:
#   bash scripts/setup_postgres.sh
#
# What this does:
#   1. Installs PostgreSQL 16
#   2. Initialises the cluster and starts the service
#   3. Creates the gaffer database, ETL user (read/write), and readonly user
#   4. Applies db/schema.sql
#   5. Prints the DATABASE_URL to add to Secrets Manager
set -euo pipefail

APP_DIR="/home/ec2-user/gaffer"
DB_NAME="gaffer"
DB_ETL_USER="gaffer_etl"
DB_READONLY_USER="gaffer_readonly"

# Generate random passwords (store these — you'll need them for Secrets Manager)
ETL_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 32)
READONLY_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 32)

echo "==> Installing PostgreSQL 16..."
sudo dnf install -y postgresql16 postgresql16-server

echo "==> Initialising PostgreSQL cluster..."
sudo postgresql-setup --initdb

echo "==> Enabling and starting PostgreSQL..."
sudo systemctl enable postgresql
sudo systemctl start postgresql

echo "==> Creating database and users..."
sudo -u postgres psql <<SQL
-- Database
CREATE DATABASE $DB_NAME;

-- ETL user (read/write — used by pipeline/etl_v2.py)
CREATE USER $DB_ETL_USER WITH PASSWORD '$ETL_PASSWORD';
GRANT CONNECT ON DATABASE $DB_NAME TO $DB_ETL_USER;

-- Readonly user (used by the FastAPI app / query_database tool)
CREATE USER $DB_READONLY_USER WITH PASSWORD '$READONLY_PASSWORD';
GRANT CONNECT ON DATABASE $DB_NAME TO $DB_READONLY_USER;

-- Connect to the gaffer database and grant schema permissions
\c $DB_NAME

GRANT USAGE ON SCHEMA public TO $DB_ETL_USER;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO $DB_ETL_USER;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO $DB_ETL_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO $DB_ETL_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO $DB_ETL_USER;

GRANT USAGE ON SCHEMA public TO $DB_READONLY_USER;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO $DB_READONLY_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO $DB_READONLY_USER;
SQL

echo "==> Applying schema..."
sudo -u postgres psql -d $DB_NAME < "$APP_DIR/db/schema.sql"

echo "==> Verifying tables..."
sudo -u postgres psql -d $DB_NAME -c "\dt"

echo ""
echo "================================================================"
echo " PostgreSQL setup complete!"
echo ""
echo " Add these to AWS Secrets Manager (gaffer/production):"
echo ""
echo "   DATABASE_URL=postgresql://$DB_READONLY_USER:$READONLY_PASSWORD@localhost:5432/$DB_NAME"
echo "   DATABASE_ETL_URL=postgresql://$DB_ETL_USER:$ETL_PASSWORD@localhost:5432/$DB_NAME"
echo ""
echo " Then run the ETL:"
echo "   cd $APP_DIR"
echo "   DATABASE_URL=postgresql://$DB_ETL_USER:$ETL_PASSWORD@localhost:5432/$DB_NAME \\"
echo "     .venv/bin/python -m pipeline.etl_v2 --mode=full"
echo ""
echo " And backfill one season at a time (one per day to stay within API limits):"
echo "   .venv/bin/python -m pipeline.etl_v2 --mode=backfill --season=2024"
echo "   .venv/bin/python -m pipeline.etl_v2 --mode=backfill --season=2023"
echo "   .venv/bin/python -m pipeline.etl_v2 --mode=backfill --season=2022"
echo "================================================================"
