"""Tests for pipeline/backup_db.py."""

from unittest.mock import MagicMock, patch

import pytest

from pipeline.backup_db import run


class TestRun:
    def test_raises_when_database_url_missing(self):
        with patch("pipeline.backup_db.settings") as mock_settings:
            mock_settings.database_url = ""
            with pytest.raises(RuntimeError, match="DATABASE_URL"):
                run()

    @patch("pipeline.backup_db.shutil.which", return_value=None)
    def test_raises_when_pg_dump_missing(self, mock_which):
        with patch("pipeline.backup_db.settings") as mock_settings:
            mock_settings.database_url = "postgres://user@host/db"
            with pytest.raises(RuntimeError, match="pg_dump"):
                run()

    @patch("pipeline.backup_db.boto3.client")
    @patch("pipeline.backup_db.subprocess.run")
    @patch("pipeline.backup_db.shutil.which", return_value="/usr/bin/pg_dump")
    def test_dumps_gzips_and_uploads_to_s3(self, mock_which, mock_run, mock_boto_client):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        def fake_pg_dump(cmd, stdout, stderr, check):
            stdout.write(b"-- fake sql dump --")
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_pg_dump

        with patch("pipeline.backup_db.settings") as mock_settings:
            mock_settings.database_url = "postgres://user@host/db"
            mock_settings.db_backup_bucket = "gaffer-db-backups-test"
            result = run()

        mock_run.assert_called_once()
        assert mock_run.call_args.args[0][0] == "pg_dump"
        mock_s3.upload_file.assert_called_once()
        args, _ = mock_s3.upload_file.call_args
        assert args[1] == "gaffer-db-backups-test"
        assert args[2].startswith("db-backups/gaffer-")
        assert args[2].endswith(".sql.gz")
        assert result["bucket"] == "gaffer-db-backups-test"
        assert result["size_bytes"] > 0

    @patch("pipeline.backup_db.boto3.client")
    @patch("pipeline.backup_db.subprocess.run")
    @patch("pipeline.backup_db.shutil.which", return_value="/usr/bin/pg_dump")
    def test_raises_with_pg_dump_stderr_on_failure(self, mock_which, mock_run, mock_boto_client):
        mock_run.return_value = MagicMock(
            returncode=1, stderr=b"permission denied for sequence fixtures_id_seq"
        )

        with patch("pipeline.backup_db.settings") as mock_settings:
            mock_settings.database_url = "postgres://user@host/db"
            with pytest.raises(RuntimeError, match="permission denied for sequence"):
                run()

        mock_boto_client.return_value.upload_file.assert_not_called()
