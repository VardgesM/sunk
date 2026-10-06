"""Run on the deployment host in a dedicated venv; never inside the application API."""

import argparse
import json
import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock, Timeout

from app.updates.compose import CloudCompose, HostConfig
from app.updates.engine import install, interrupted
from app.updates.schema import ACTIVE
from app.updates.store import UpdateStore, atomic_json

logger = logging.getLogger(__name__)


def run(config: HostConfig, *, once: bool = False) -> None:
    store = UpdateStore(config.shared_directory)
    deployment = CloudCompose(config, store)
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.is_set():
            atomic_json(
                store.root / "runner.json",
                {"handler": config.handler, "heartbeat": datetime.now(UTC).isoformat()},
            )
            stop.wait(5)

    with FileLock(store.root / "runner.lock", timeout=0):
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            while True:
                try:
                    with store.lock():
                        status = store.read()
                        if status.state == "READY":
                            if (
                                not status.updated_at
                                or (datetime.now(UTC) - status.updated_at).total_seconds() > 900
                            ):
                                store.write(
                                    status,
                                    state="FAILED",
                                    failure_stage="READY",
                                    error="Prepared update expired; check and request installation again",
                                )
                            else:
                                install(store, status, deployment)
                        elif (
                            status.state in ACTIVE
                            and status.updated_at
                            and (datetime.now(UTC) - status.updated_at).total_seconds() > 60
                        ):
                            # Preparation holds operation.lock. A free lock + expired handoff
                            # identifies an interrupted process, never a reason to replay installation.
                            interrupted(store, status, deployment)
                except Timeout:
                    pass  # API is downloading/backing up; do not race its secret-bearing work.
                if once:
                    return
                time.sleep(2)
        finally:
            stop.set()
            thread.join()
            (store.root / "runner.json").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manual-update host runner; only processes ADMIN-approved jobs"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    try:
        config = HostConfig.model_validate_json(args.config.read_bytes())
        if args.status:
            print(
                json.dumps(
                    UpdateStore(config.shared_directory).read().model_dump(mode="json"), indent=2
                )
            )
        else:
            run(config, once=args.once)
    except (Exception, KeyboardInterrupt) as exc:
        # No command output or config values: Docker/environment exceptions can include secrets.
        raise SystemExit(
            f"Updater stopped ({type(exc).__name__}); inspect journal and deployment documentation"
        ) from None


if __name__ == "__main__":
    main()
