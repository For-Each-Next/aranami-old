"""Sample one Toolforge service without retaining its workload data."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from threading import Event, Thread
from typing import TYPE_CHECKING

from data.runtime.server_samples import save_job_sample
from shared.support.resources import sample_container

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Iterator
    from pathlib import Path

_LOGGER = logging.getLogger(__name__)
_SAMPLE_SECONDS = 10


@contextmanager
def observe_job(
    runtime: Path,
    name: str,
    started: dt.datetime,
) -> Iterator[None]:
    """Sample this container during one owned invocation."""
    stopped = Event()

    def record(outcome: str) -> None:
        """Publish optional readings independently of the work."""
        try:
            save_job_sample(
                runtime,
                name,
                started,
                outcome,
                sample_container(),
            )
        except OSError, ValueError:
            _LOGGER.warning("Could not record resource usage for %s.", name)

    def sample() -> None:
        """Refresh live usage until the invocation finishes."""
        while not stopped.wait(_SAMPLE_SECONDS):
            record("running")

    record("running")
    monitor = Thread(target=sample, daemon=True)
    monitor.start()
    outcome = "failed"
    try:
        yield
        outcome = "succeeded"
    finally:
        stopped.set()
        monitor.join()
        record(outcome)
