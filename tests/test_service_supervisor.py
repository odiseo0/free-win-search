from __future__ import annotations

import signal
import subprocess
from collections.abc import Iterator
from typing import cast

from src.service_supervisor import Service, ServiceSupervisor, build_services


class FakeProcess:
    next_pid = 100

    def __init__(self, statuses: Iterator[int | None]) -> None:
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1
        self._statuses = statuses
        self._status: int | None = None
        self.signals: list[int] = []
        self.waited = False
        self.terminated = False

    def poll(self) -> int | None:
        if self.terminated:
            return self._status

        try:
            self._status = next(self._statuses)
        except StopIteration:
            pass

        return self._status

    def send_signal(self, signum: int) -> None:
        self.signals.append(signum)
        self._status = 0
        self.terminated = True

    def kill(self) -> None:
        self.send_signal(9)

    def wait(self) -> int:
        self.waited = True

        return self._status or 0


def test_build_services_starts_api_and_scraper() -> None:
    services = build_services({}, executable="python")

    assert [service.name for service in services] == ["api", "scraper"]
    assert services[0].command[-1] == "8000"


def test_build_services_uses_port_and_adds_meilisearch_worker() -> None:
    services = build_services(
        {"PORT": "9000", "SEARCH_BACKEND": "MEILISEARCH"},
        executable="python",
    )

    assert [service.name for service in services] == [
        "api",
        "scraper",
        "search-index",
    ]
    assert services[0].command[-1] == "9000"


def test_worker_failure_stops_other_processes(monkeypatch) -> None:
    api = FakeProcess(iter([None, None, None]))
    scraper = FakeProcess(iter([7]))
    processes = iter([api, scraper])
    supervisor = ServiceSupervisor(
        [Service("api", ("api",)), Service("scraper", ("scraper",))],
        shutdown_timeout_seconds=0,
    )

    monkeypatch.setattr(
        "src.service_supervisor.subprocess.Popen",
        lambda *_args, **_kwargs: next(processes),
    )
    monkeypatch.setattr(
        supervisor,
        "_signal",
        lambda process, signum: process.send_signal(signum),
    )
    monkeypatch.setattr(supervisor, "_kill", lambda process: process.kill())
    monkeypatch.setattr("src.service_supervisor.signal.signal", lambda *_: None)
    monkeypatch.setattr("src.service_supervisor.time.sleep", lambda _: None)

    assert supervisor.run() == 7
    assert api.signals == [signal.SIGTERM, 9]
    assert api.waited
    assert scraper.waited


def test_shutdown_signal_stops_all_processes(monkeypatch) -> None:
    api = FakeProcess(iter([None, None]))
    scraper = FakeProcess(iter([None, None]))
    supervisor = ServiceSupervisor([], shutdown_timeout_seconds=1)
    supervisor.processes = {
        "api": cast(subprocess.Popen[bytes], api),
        "scraper": cast(subprocess.Popen[bytes], scraper),
    }

    monkeypatch.setattr(
        supervisor,
        "_signal",
        lambda process, signum: process.send_signal(signum),
    )

    supervisor.request_shutdown(signal.SIGTERM)
    supervisor.stop()

    assert supervisor.shutdown_requested
    assert api.signals == [signal.SIGTERM]
    assert scraper.signals == [signal.SIGTERM]
    assert api.waited
    assert scraper.waited
