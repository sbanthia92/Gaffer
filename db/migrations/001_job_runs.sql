-- Migration 001: job_runs table
-- Records every attempt/success/failure for background cron jobs.
-- Apply on EC2: psql $DATABASE_ETL_URL -f db/migrations/001_job_runs.sql

CREATE TABLE IF NOT EXISTS job_runs (
    id           SERIAL PRIMARY KEY,
    job_name     TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('attempt', 'success', 'failure')),
    gw_number    INTEGER,
    details      JSONB NOT NULL DEFAULT '{}',
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_job_runs_job_name_started
    ON job_runs (job_name, started_at DESC);
