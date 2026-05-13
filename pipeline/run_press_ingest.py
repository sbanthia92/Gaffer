"""
Wrapper that loads secrets via the Gaffer's config mechanism then runs
the sports-context-mcp press ingestion job.

On EC2 (ENVIRONMENT=production), server.config._inject_secrets() fetches
all secrets from AWS Secrets Manager and injects them into os.environ.
The MCP package's config reads them lazily via os.getenv, so secrets are
available by the time run() is called.
"""

import logging
import sys

from jobs.ingest_press_content import run

import server.config  # noqa: F401 — side-effect: injects secrets into os.environ
from pipeline.job_metrics import record_attempt, record_failure, record_success

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

if __name__ == "__main__":
    run_id = record_attempt("press_ingest")
    try:
        result = run()
        record_success(run_id, result if isinstance(result, dict) else {})
    except Exception as exc:
        record_failure(run_id, str(exc))
        sys.exit(1)
