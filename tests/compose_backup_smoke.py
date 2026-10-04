"""Disposable real PostgreSQL backup/recovery integration; never attaches production volumes."""

import os
import secrets
import subprocess
import time
from pathlib import Path
from uuid import uuid4


def main() -> None:
    suffix = uuid4().hex[:12]
    network, database = "backup-test-" + suffix, "backup-pg-" + suffix
    environment = {**os.environ, "POSTGRES_PASSWORD": secrets.token_urlsafe(32)}

    def run(*args: str) -> str:
        result = subprocess.run(["docker", *args], env=environment, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout

    try:
        run("network", "create", network)
        run(
            "run",
            "-d",
            "--name",
            database,
            "--network",
            network,
            "--tmpfs",
            "/var/lib/postgresql/data",
            "-e",
            "POSTGRES_PASSWORD",
            "-e",
            "POSTGRES_USER=backup_test",
            "-e",
            "POSTGRES_DB=backup_test_data",
            "postgres:17-alpine",
        )
        for _ in range(60):
            ready = subprocess.run(
                ["docker", "exec", database, "pg_isready", "-U", "backup_test"], capture_output=True
            )
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        output = run(
            "run",
            "--rm",
            "--network",
            network,
            "--mount",
            f"type=bind,source={Path('tests/backup_postgres_smoke.py').resolve()},target=/tmp/backup_test.py,readonly",
            "--mount",
            f"type=bind,source={Path('server/app').resolve()},target=/app/app,readonly",
            "-e",
            "APP_MODE=standalone",
            "-e",
            "MODBUS_WRITES_ENABLED=false",
            "-e",
            "TELEMETRY_SOURCE=disabled",
            "-e",
            "LIVE_UPDATES_ENABLED=false",
            "-e",
            "TELEGRAM_ENABLED=false",
            "-e",
            "POSTGRES_PASSWORD",
            "-e",
            f"POSTGRES_HOST={database}",
            "-e",
            "POSTGRES_USER=backup_test",
            "-e",
            "POSTGRES_DB=backup_test_data",
            "-e",
            "BACKUP_DIRECTORY=/var/lib/modbus-monitor/backups",
            "-e",
            "PYTHONPATH=/app",
            "modbus-phase12-test",
            "python",
            "/tmp/backup_test.py",
        )
        print(output)
    finally:
        subprocess.run(["docker", "rm", "-f", database], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)


if __name__ == "__main__":
    main()
