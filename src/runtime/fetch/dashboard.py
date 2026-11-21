"""Collect dashboard snapshots under an exclusive output lease."""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import logging
import os
import stat
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from data.runtime.events import event_extra
from data.runtime.logs import open_run_log
from data.runtime.status import record_dataset
from data.website import read_snapshot
from runtime.observability.collection_status import (
    CollectionExecution,
    collection_run,
)
from shared.support.dataset_activity import dataset_activity

if TYPE_CHECKING:
    from collections.abc import Callable

    type Snapshot = dict[str, object]
    type Collector = Callable[[], Snapshot]
    type Saver = Callable[[Path, Snapshot], None]

_LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    """Return a UTC timestamp for refresh observations."""
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class DashboardUpdater:
    """Collect serially and retain the last successful snapshot."""

    def __init__(
        self,
        output: Path,
        collect: Collector,
        save: Saver,
        *,
        log_dir: Path = Path("logs"),
        runtime: Path | None = None,
    ) -> None:
        """Configure an updater without starting collection.

        Args:
            output: Snapshot path shared with the read-only website.
            collect: Read-only callback returning the next snapshot.
            save: Atomic writer called only after collection succeeds.
            log_dir: Directory for the shared daily diagnostic log.
            runtime: Status home, defaulting to the standalone output
            folder.
        """
        self.output = output.resolve()
        self._runtime = (runtime or self.output.parent).resolve()
        self._collect = collect
        self._save = save
        self._log_dir = log_dir
        self._logs = ExitStack()
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._state: dict[str, str | bool | None] = {
            "last_attempt": None,
            "last_success": None,
            "last_error": None,
            "refreshing": False,
        }
        self._lock_fd: int | None = None
        self._started = False

    @property
    def stopping(self) -> bool:
        """Whether graceful shutdown has been requested."""
        return self._stop.is_set()

    def start(self) -> None:
        """Claim the output for this collector.

        Raises:
            RuntimeError: Already started or unable to own the output.
        """
        if self._started:
            message = "This dashboard updater has already been started."
            raise RuntimeError(message)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.output.with_name(self.output.name + ".lock")
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        try:
            self._claim_lock(descriptor)
            self._lock_fd = descriptor
            self._logs.enter_context(open_run_log(self._log_dir))
            _LOGGER.info(
                "Website collector started.",
                extra=event_extra("service_started", service="website"),
            )
        except BaseException:
            self._logs.close()
            self._lock_fd = None
            os.close(descriptor)
            raise
        self._started = True

    def request_stop(self) -> None:
        """Reject queued refreshes while active collection finishes.

        Ownership and log handles remain open until ``stop`` drains the
        collector. This nonblocking step precedes scheduler shutdown.
        """
        if not self._stop.is_set():
            self._stop.set()
            _LOGGER.info(
                "Website collection stopping; queued refreshes will be "
                "skipped and active collection will finish before release.",
            )

    def stop(self) -> None:
        """Finish the active refresh and release resources."""
        self.request_stop()
        with self._refresh_lock:
            if self._lock_fd is not None:
                _LOGGER.info(
                    "Website collector stopped.",
                    extra=event_extra("service_stopped", service="website"),
                )
                os.close(self._lock_fd)
                self._lock_fd = None
            self._logs.close()

    def health(self) -> dict[str, str | bool | None]:
        """Return the latest attempt and saved-refresh state.

        Returns:
            Timestamps, error type, refresh state, and readiness.
            Readiness requires a saved refresh in this process.
        """
        with self._state_lock:
            state = self._state.copy()
        state["healthy"] = (
            state["last_success"] is not None and state["last_error"] is None
        )
        return state

    def snapshot_bytes(self) -> bytes | None:
        """Read bounded JSON without following a snapshot symlink.

        Returns:
            Saved JSON bytes, or None for unavailable or invalid data.
        """
        try:
            content = json.dumps(
                read_snapshot(self.output),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        except OSError, ValueError:
            return None
        try:
            valid = isinstance(json.loads(content), dict)
        except ValueError:
            return None
        if not valid:
            return None
        return content

    @staticmethod
    def _claim_lock(descriptor: int) -> None:
        """Exclusively lock a regular file.

        Raises:
            RuntimeError: The lock is invalid or already held.
        """
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            message = "The updater lock must be a regular file."
            raise RuntimeError(message)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            message = "Another updater already owns this dashboard output."
            raise RuntimeError(message) from error

    def refresh(
        self,
        *,
        wait: bool = False,
        task_id: str = "website",
        trigger: str = "unknown",
    ) -> bool:
        """Attempt one collection while skipping overlapping refreshes.

        Collection failures retain the previous snapshot and record the
        error type. Each website section follows its own schedule.

        Args:
            wait: Queue behind active work for a calendar refresh.
            task_id: Actual collection job responsible for this refresh.
            trigger: Known invocation cause, otherwise unknown.

        Returns:
            Whether a complete snapshot was saved. False also covers
            an overlapping attempt or a requested shutdown.

        Raises:
            RuntimeError: The updater has not acquired its output lock.
        """
        if self._stop.is_set():
            return False
        if self._lock_fd is None:
            message = "Start the dashboard updater before refreshing."
            raise RuntimeError(message)
        if not self._refresh_lock.acquire(blocking=wait):
            return False
        try:
            if self._stop.is_set():
                return False
            return self._refresh(task_id, trigger)
        finally:
            self._refresh_lock.release()

    def _refresh(self, task_id: str, trigger: str) -> bool:
        """Collect under one correlated execution and ownership lease.

        Returns:
            Whether collection and persistence succeeded.
        """
        with collection_run(
            task_id,
            runtime=self._runtime,
            trigger=trigger,
        ) as execution:
            return self._refresh_observed(execution)

    def _refresh_observed(self, execution: CollectionExecution) -> bool:
        """Collect once while the refresh and output locks are held.

        Returns:
            Whether collection and atomic persistence both succeeded.
        """
        started = time.monotonic()
        with self._state_lock:
            self._state.update(last_attempt=_utc_now(), refreshing=True)
        _LOGGER.info(
            "Website refresh started.",
            extra=event_extra("website_started"),
        )
        try:
            dataset_activity("begin", self.output)
            snapshot = self._collect_snapshot()
            self._save(self.output, snapshot)
        except Exception as error:  # ruff: ignore[blind-except]
            execution.fail(error)
            kind = type(error).__name__
            with self._state_lock:
                self._state["last_error"] = kind
            elapsed = time.monotonic() - started
            _LOGGER.log(
                logging.ERROR,
                "Website refresh failed after %.3f seconds (%s). "
                "Previous data was retained.",
                elapsed,
                kind,
                extra=event_extra(
                    "website_finished",
                    status="failed",
                    failures=None,
                    duration_seconds=elapsed,
                ),
            )
            return False
        else:
            with self._state_lock:
                self._state.update(last_success=_utc_now(), last_error=None)
            errors = snapshot.get("errors", [])
            collection = snapshot.get("collection")
            source_failures = (
                collection["failed"]
                if isinstance(collection, dict)
                else len(errors)
                if isinstance(errors, list)
                else None
            )
            if source_failures != 0:
                execution.fail()
            self._record_datasets(snapshot)
            elapsed = time.monotonic() - started
            if source_failures == 0:
                _LOGGER.info(
                    "Website refresh completed in %.3f seconds.",
                    elapsed,
                    extra=event_extra(
                        "website_finished",
                        status="updated",
                        failures=0,
                        duration_seconds=elapsed,
                    ),
                )
            elif source_failures is None:
                _LOGGER.warning(
                    "Website refresh completed in %.3f seconds; "
                    "the source failure count is unavailable.",
                    elapsed,
                    extra=event_extra(
                        "website_finished",
                        status="unconfirmed",
                        failures=None,
                        duration_seconds=elapsed,
                    ),
                )
            else:
                _LOGGER.warning(
                    "Website refresh completed in %.3f seconds with %d "
                    "source failure%s. Previous data was retained for "
                    "failed reports.",
                    elapsed,
                    source_failures,
                    "" if source_failures == 1 else "s",
                    extra=event_extra(
                        "website_finished",
                        status="partial",
                        failures=source_failures,
                        duration_seconds=elapsed,
                    ),
                )
            return True
        finally:
            with self._state_lock:
                self._state["refreshing"] = False

    def _record_datasets(self, snapshot: Snapshot) -> None:
        """Retain each accepted dataset's original observation clock.

        Args:
            snapshot: Presentation data whose atomic save succeeded.
        """
        for name, source in snapshot.get("reports", {}).items():
            observed = source.get("last_success_at")
            if observed is None:
                continue
            interval = source.get("refresh_interval_seconds")
            record_dataset(
                {
                    "family": f"website-{name}",
                    "generation": observed,
                    "calculated_at": observed,
                    "target": {"site": "zhwiki", "title": name},
                    "metadata": {},
                },
                runtime=self._runtime,
                policy="interval",
                max_age_seconds=int(interval)
                if interval is not None
                else None,
            )

    def _collect_snapshot(self) -> Snapshot:
        """Collect and validate a snapshot before saving.

        Returns:
            The callback's complete presentation snapshot.

        Raises:
            TypeError: The callback returned a non-dictionary value.
        """
        snapshot = self._collect()
        if not isinstance(snapshot, dict):
            message = "A collector must return a snapshot dictionary."
            raise TypeError(message)
        return snapshot


def collect_dashboard_pass(
    updater: DashboardUpdater,
    collect: Callable[..., Snapshot],
    save: Saver,
    days: int,
    refresh_intervals: dict[str, float] | None = None,
) -> Snapshot:
    """Publish progress for a pass starting without saved data.

    Args:
        updater: Owner of the output and its last readable snapshot.
        collect: Collector accepting the optional progress callback.
        save: Atomic snapshot writer used for initial progress.
        days: UTC dates included in the collection window.
        refresh_intervals: Per-report refresh intervals in seconds.

    Returns:
        The final snapshot. Existing data remains unchanged
        until the updater commits a successful final result.
    """

    def publish(snapshot: Snapshot) -> None:
        """Commit initial sections through the atomic writer."""
        save(updater.output, snapshot)

    publisher = publish if updater.snapshot_bytes() is None else None
    options = (
        {"refresh_intervals": refresh_intervals}
        if refresh_intervals is not None
        else {}
    )
    return collect(
        dt.datetime.now(dt.UTC).date(),
        days,
        publish=publisher,
        cache_directory=updater.output.parent,
        **options,
    )
