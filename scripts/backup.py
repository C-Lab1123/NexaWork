import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "QueshStandards.settings")
django.setup()

from django.conf import settings


def _backup_database(destination):
    database = settings.DATABASES["default"]
    engine = database["ENGINE"]

    if engine == "django.db.backends.sqlite3":
        source = Path(database["NAME"])
        if not source.is_file():
            raise FileNotFoundError(f"SQLite database does not exist: {source}")
        with sqlite3.connect(source) as source_connection, sqlite3.connect(destination) as target_connection:
            source_connection.backup(target_connection)
        return

    if engine == "django.db.backends.postgresql":
        command = [
            "pg_dump",
            "--no-password",
            "--format=custom",
            "--file",
            str(destination),
        ]
        if database.get("HOST"):
            command.extend(["--host", str(database["HOST"])])
        if database.get("PORT"):
            command.extend(["--port", str(database["PORT"])])
        if database.get("USER"):
            command.extend(["--username", str(database["USER"])])
        command.extend(["--dbname", str(database["NAME"])])
        environment = os.environ.copy()
        if database.get("PASSWORD"):
            environment["PGPASSWORD"] = database["PASSWORD"]
        subprocess.run(command, env=environment, check=True)
        return

    raise ValueError(f"Database engine is not supported by this backup script: {engine}")


def _remove_expired_backups(backup_root, retention_days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    for path in backup_root.iterdir():
        if not path.is_dir() or not path.name.startswith("backup-"):
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            shutil.rmtree(path)


def main():
    retention_days = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
    if retention_days < 1:
        raise ValueError("BACKUP_RETENTION_DAYS must be at least 1.")

    backup_root = Path(os.getenv("BACKUP_DIR", settings.BASE_DIR / "backups")).expanduser().resolve()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if backup_root == media_root or media_root in backup_root.parents:
        raise ValueError("BACKUP_DIR must not be inside MEDIA_ROOT.")

    if os.name == "posix":
        os.umask(0o077)
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    staging = backup_root / f".backup-{timestamp}.incomplete"
    destination = backup_root / f"backup-{timestamp}"
    staging.mkdir(mode=0o700)

    try:
        _backup_database(staging / "database.dump")
        if media_root.is_dir():
            shutil.copytree(media_root, staging / "files", symlinks=True)
        else:
            (staging / "files").mkdir()
        staging.rename(destination)
        _remove_expired_backups(backup_root, retention_days)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    print(f"Created backup at {destination}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        raise
