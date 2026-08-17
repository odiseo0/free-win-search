from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

logger = logging.getLogger("free_win.service_supervisor")

SHUTDOWN_TIMEOUT_SECONDS = 10.0
POLL_INTERVAL_SECONDS = 0.1


@dataclass(frozen=True, slots=True)
class Service:
    name: str
    command: tuple[str, ...]


def build_services(
    environment: Mapping[str, str] | None = None,
    *,
    executable: str | None = None,
) -> tuple[Service, ...]:
    env = os.environ if environment is None else environment
    python = executable or sys.executable
    port = env.get("PORT", "8000")
    services = [
        Service(
            "api",
            (
                python,
                "-m",
                "uvicorn",
                "src.application:app",
                "--host",
                "0.0.0.0",
                "--port",
                port,
            ),
        ),
        Service(
            "scraper",
            (python, "-m", "src.core.services.scraper", "worker"),
        ),
    ]

    if env.get("SEARCH_BACKEND", "postgresql").lower() == "meilisearch":
        services.append(
            Service(
                "search-index",
                (python, "-m", "src.core.services.search_index", "worker"),
            )
        )

    return tuple(services)


class ServiceSupervisor:
    def __init__(
        self,
        services: Sequence[Service],
        *,
        shutdown_timeout_seconds: float = SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        self.services = tuple(services)
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.shutdown_requested = False

    def request_shutdown(self, signum: int, _: object | None = None) -> None:
        logger.info("received signal %s", signum)
        self.shutdown_requested = True

    def start(self) -> None:
        for service in self.services:
            logger.info("starting %s", service.name)
            self.processes[service.name] = subprocess.Popen(
                service.command,
                start_new_session=os.name == "posix",
            )

    @staticmethod
    def _signal(process: subprocess.Popen[bytes], signum: int) -> None:
        if os.name == "posix":
            os.killpg(process.pid, signum)
        else:
            process.send_signal(signum)

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()

    def stop(self) -> None:
        running = [
            process for process in self.processes.values() if process.poll() is None
        ]

        for process in running:
            self._signal(process, signal.SIGTERM)

        deadline = time.monotonic() + self.shutdown_timeout_seconds

        while running and time.monotonic() < deadline:
            running = [process for process in running if process.poll() is None]

            if running:
                time.sleep(POLL_INTERVAL_SECONDS)

        for process in running:
            logger.warning("forcing process %s to stop", process.pid)
            self._kill(process)

        for process in self.processes.values():
            process.wait()

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self.request_shutdown)
        signal.signal(signal.SIGINT, self.request_shutdown)

        try:
            self.start()

            while not self.shutdown_requested:
                for name, process in self.processes.items():
                    return_code = process.poll()

                    if return_code is not None:
                        logger.error(
                            "%s stopped unexpectedly with status %s",
                            name,
                            return_code,
                        )

                        return return_code if return_code != 0 else 1

                time.sleep(POLL_INTERVAL_SECONDS)

            return 0
        except Exception:
            logger.exception("service supervisor failed")

            return 1
        finally:
            self.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    raise SystemExit(ServiceSupervisor(build_services()).run())


if __name__ == "__main__":
    main()
