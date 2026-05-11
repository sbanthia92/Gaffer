"""
Wrapper that loads secrets via the Gaffer's config mechanism then runs
the sports-context-mcp press ingestion job.

On EC2 (ENVIRONMENT=production), server.config._inject_secrets() fetches
all secrets from AWS Secrets Manager and injects them into os.environ.
The MCP package's config reads them lazily via os.getenv, so secrets are
available by the time run() is called.
"""

from jobs.ingest_press_content import run

import server.config  # noqa: F401 — side-effect: injects secrets into os.environ

if __name__ == "__main__":
    run()
