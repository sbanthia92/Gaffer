"""
Nightly Postgres backup: pg_dump -> gzip -> upload to S3.

EBS survives reboots but not instance replacement, so this is the durability
layer for that gap (see the EC2 AMI pinning gotcha in CLAUDE.md). Uses
DATABASE_URL (gaffer_readonly) since a backup only needs SELECT access, never
write access. The S3 bucket has a 30-day lifecycle expiration (terraform), so
no local retention/cleanup logic is needed here.
"""

import gzip
import logging
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import boto3

from pipeline.job_metrics import record_attempt, record_failure, record_success
from server.config import settings

# Auth tables (PII, eventually encrypted API keys) are deliberately not granted to
# gaffer_readonly (db/migrations/002_auth_tables.sql), so pg_dump as that role fails
# its LOCK TABLE on them and aborts the whole dump. Exclude them; backing them up
# needs a separate dump as gaffer_app.
_EXCLUDED_TABLES = ("users", "device_tokens", "conversations", "chat_messages")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run() -> dict:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set")
    if shutil.which("pg_dump") is None:
        raise RuntimeError("pg_dump not found on PATH")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    key = f"db-backups/gaffer-{timestamp}.sql.gz"

    with tempfile.TemporaryDirectory() as tmp:
        dump_path = Path(tmp) / "gaffer.sql"
        gz_path = Path(tmp) / "gaffer.sql.gz"

        with dump_path.open("wb") as f:
            proc = subprocess.run(
                [
                    "pg_dump",
                    settings.database_url,
                    "--no-owner",
                    "--no-privileges",
                    *(f"--exclude-table=public.{t}" for t in _EXCLUDED_TABLES),
                ],
                stdout=f,
                stderr=subprocess.PIPE,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"pg_dump failed: {proc.stderr.decode().strip()}")

        with dump_path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

        size_bytes = gz_path.stat().st_size
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.upload_file(str(gz_path), settings.db_backup_bucket, key)

    log.info(
        "db backup uploaded: s3://%s/%s (%d bytes)", settings.db_backup_bucket, key, size_bytes
    )
    return {"bucket": settings.db_backup_bucket, "key": key, "size_bytes": size_bytes}


if __name__ == "__main__":
    run_id = record_attempt("db_backup")
    try:
        result = run()
        record_success(run_id, result)
    except Exception as exc:
        log.error("db backup failed: %s", exc)
        record_failure(run_id, str(exc))
        sys.exit(1)
