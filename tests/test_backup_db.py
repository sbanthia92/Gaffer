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
            mock_settings.database_app_url = ""
            mock_settings.db_backup_bucket = "gaffer-db-backups-test"
            result = run()

        # No DATABASE_APP_URL: only the main dump runs
        mock_run.assert_called_once()
        assert "auth_key" not in result
        assert mock_run.call_args.args[0][0] == "pg_dump"
        # gaffer_readonly has no grants on the auth tables — dumping them aborts pg_dump
        for table in (
            "users",
            "device_tokens",
            "conversations",
            "chat_messages",
            "daily_question_counts",
        ):
            assert f"--exclude-table=public.{table}" in mock_run.call_args.args[0]
            assert f"--exclude-table=public.{table}_id_seq" in mock_run.call_args.args[0]
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

    @patch("pipeline.backup_db.boto3.client")
    @patch("pipeline.backup_db.subprocess.run")
    @patch("pipeline.backup_db.shutil.which", return_value="/usr/bin/pg_dump")
    def test_dumps_app_tables_separately_as_gaffer_app(
        self, mock_which, mock_run, mock_boto_client
    ):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        def fake_pg_dump(cmd, stdout, stderr, check):
            stdout.write(b"-- fake sql dump --")
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_pg_dump

        with patch("pipeline.backup_db.settings") as mock_settings:
            mock_settings.database_url = "postgres://readonly@host/db"
            mock_settings.database_app_url = "postgres://app@host/db"
            mock_settings.db_backup_bucket = "gaffer-db-backups-test"
            result = run()

        assert mock_run.call_count == 2
        main_cmd, auth_cmd = (call.args[0] for call in mock_run.call_args_list)
        assert main_cmd[1] == "postgres://readonly@host/db"
        assert auth_cmd[1] == "postgres://app@host/db"
        for table in (
            "users",
            "device_tokens",
            "conversations",
            "chat_messages",
            "daily_question_counts",
        ):
            assert f"--table=public.{table}" in auth_cmd
        assert not any(arg.startswith("--exclude-table") for arg in auth_cmd)

        keys = [call.args[2] for call in mock_s3.upload_file.call_args_list]
        assert keys == [result["key"], result["auth_key"]]
        assert result["auth_key"].startswith("db-backups/gaffer-auth-")
        assert result["auth_size_bytes"] > 0

    @patch("pipeline.backup_db.boto3.client")
    @patch("pipeline.backup_db.subprocess.run")
    @patch("pipeline.backup_db.shutil.which", return_value="/usr/bin/pg_dump")
    def test_app_table_dump_failure_fails_the_job(self, mock_which, mock_run, mock_boto_client):
        def fake_pg_dump(cmd, stdout, stderr, check):
            if cmd[1] == "postgres://app@host/db":
                return MagicMock(returncode=1, stderr=b"permission denied for table users")
            stdout.write(b"-- fake sql dump --")
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_pg_dump

        with patch("pipeline.backup_db.settings") as mock_settings:
            mock_settings.database_url = "postgres://readonly@host/db"
            mock_settings.database_app_url = "postgres://app@host/db"
            mock_settings.db_backup_bucket = "gaffer-db-backups-test"
            with pytest.raises(RuntimeError, match="permission denied for table users"):
                run()
