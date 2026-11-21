"""Coordinate source collection and wiki and website outputs.

Run :func:`main` to start one runtime process with independent wiki
schedules, due website collection, and local read-only HTTP endpoints.
Wiki and website work in the same dispatch share successful source
observations. Website requests only read persisted results.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import math
import signal
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from time import monotonic
from typing import TYPE_CHECKING

from data.runtime.events import event_extra
from data.runtime.logs import open_run_log
from runtime.backfills.quality_analysis import schedule_quality_analysis
from runtime.fetch.consistency_repairs import refresh_saved_repairs
from runtime.fetch.dashboard import DashboardHTTPServer
from runtime.fetch.newsletter_history import run as refresh_article_history
from runtime.fetch.project_data import run as refresh_project_data
from runtime.fetch.website import (
    DEFAULT_DAYS,
    DEFAULT_OUTPUT,
    dashboard_updater,
    refresh_newsletter,
    refresh_website,
)
from runtime.scheduling import monitor
from shared.config import COLLECTION_DEFINITIONS
from shared.deployment import project_version
from shared.identity import configure_pywikibot
from tasks.website.collect import (
    add_refresh_arguments,
    refresh_arguments,
    report_intervals,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import FrameType

    from apscheduler.schedulers.background import BackgroundScheduler

    from runtime.fetch.dashboard import DashboardUpdater
    from runtime.scheduling.idle_scheduler import IdleScheduler

_MAX_DAYS = 365
_MAX_PORT = 65535
_WEBSITE_CHECK_SECONDS = 3600
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HubConfig:
    """Configure one runtime process and its persisted website outputs.

    Attributes:
        dry: Generate wiki previews without website writes or serving.
        run_immediately: Check both outputs before their first trigger.
        output: Saved Parquet for the website and local HTTP endpoint.
        log_dir: Directory for process diagnostics and website lifecycle
            records.
        interval: Website check seconds; the default follows UTC hours.
        days: UTC dates in the website collection window.
        host: Local interface serving saved data and health.
        port: HTTP port; zero selects an available port for tests.
        refresh_intervals: Website report refresh periods in seconds.
    """

    dry: bool = False
    run_immediately: bool = True
    output: Path = DEFAULT_OUTPUT
    log_dir: Path = Path("logs")
    interval: float = _WEBSITE_CHECK_SECONDS
    days: int = DEFAULT_DAYS
    host: str = "127.0.0.1"
    port: int = 8765
    refresh_intervals: dict[str, float] | None = None

    def __post_init__(self) -> None:
        """Validate collection settings before starting any output.

        Raises:
            ValueError: An interval, date window, or port is invalid.
        """
        if not math.isfinite(self.interval) or self.interval <= 0:
            message = "--interval must be positive and finite."
            raise ValueError(message)
        if not 1 <= self.days <= _MAX_DAYS:
            message = "--days must be between 1 and 365."
            raise ValueError(message)
        if not 0 <= self.port <= _MAX_PORT:
            message = "--port must be between 0 and 65535."
            raise ValueError(message)
        report_intervals(self.refresh_intervals)


def stop_jobs(
    scheduler: BackgroundScheduler,
    updater: DashboardUpdater | None,
) -> None:
    """Drain running jobs before releasing service resources.

    Pause new scheduled dispatches and reject queued website refreshes.
    Active work retains its locks, logs, and publication observations
    until it finishes. Existing report completion logs identify each
    invocation's outcome; the final message confirms completion.

    Args:
        scheduler: Scheduler owned by the stopping hub.
        updater: Website output owner, absent in preview mode.
    """
    if not scheduler.running:
        return
    started = monotonic()
    scheduler.pause()
    if updater is not None:
        updater.request_stop()
    _LOGGER.info(
        "Scheduled dispatch paused; waiting for running jobs to finish "
        "and persist their final status.",
    )
    scheduler.shutdown(wait=True)
    _LOGGER.info(
        "All running jobs stopped safely after %.2f seconds; "
        "final job status and logs are saved.",
        monotonic() - started,
    )


def _serve_until_stopped(
    server: DashboardHTTPServer | None,
    scheduler: BackgroundScheduler,
    updater: DashboardUpdater | None,
    stopped: Event,
    control: dict[str, bool],
) -> None:
    """Serve observations while honoring drain and stop signals."""
    if server is None:
        stopped.wait()
        return
    drained = False
    while not stopped.is_set():
        if control["drain"] and not drained:
            _LOGGER.info(
                "Deployment requested a safe hub drain; "
                "keeping the pod alive until work is saved.",
            )
            stop_jobs(scheduler, updater)
            updater.confirm_drained()
            drained = True
            _LOGGER.info("Hub drain confirmed; waiting for termination.")
        server.handle_request()


def _schedule_collections(
    scheduler: IdleScheduler,
    updater: DashboardUpdater,
    config: HubConfig,
) -> None:
    """Register collection owners before the hub resumes dispatch."""
    project = COLLECTION_DEFINITIONS["project-data"]
    scheduler.add_job(
        refresh_project_data,
        trigger="cron",
        hour=project.hour,
        minute=project.minute,
        second=0,
        timezone=dt.UTC,
        id="project-data",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
        **(
            {"next_run_time": dt.datetime.now(dt.UTC)}
            if config.run_immediately
            else {}
        ),
    )
    history = COLLECTION_DEFINITIONS["newsletter-history"]
    scheduler.add_job(
        refresh_article_history,
        trigger="cron",
        hour=history.hour,
        minute=history.minute,
        second=0,
        timezone=dt.UTC,
        id="newsletter-history",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )
    newsletter = COLLECTION_DEFINITIONS["newsletter-daily"]
    scheduler.add_job(
        refresh_newsletter,
        trigger="cron",
        hour=newsletter.hour,
        minute=newsletter.minute,
        second=0,
        timezone=dt.UTC,
        id="newsletter-daily",
        args=(updater,),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )
    startup = (
        {"next_run_time": dt.datetime.now(dt.UTC)}
        if config.run_immediately
        else {}
    )
    schedule_quality_analysis(
        scheduler,
        run_immediately=config.run_immediately,
    )
    scheduler.add_job(
        refresh_website,
        **(
            {
                "trigger": "cron",
                "hour": COLLECTION_DEFINITIONS["website"].hour,
                "minute": COLLECTION_DEFINITIONS["website"].minute,
                "second": 0,
                "timezone": dt.UTC,
            }
            if config.interval == _WEBSITE_CHECK_SECONDS
            else {"trigger": "interval", "seconds": config.interval}
        ),
        id="website",
        args=(updater,),
        max_instances=1,
        coalesce=True,
        **startup,
    )


def run(config: HubConfig) -> None:
    """Serve saved data and coordinate updates until a shutdown signal.

    One scheduler owns report tasks and website-only due checks. On
    SIGINT, SIGTERM, or a failed HTTP loop, shutdown waits for active
    tasks before releasing website ownership and closing HTTP. Preview
    mode starts only report schedules and writes no production data.

    Args:
        config: Validated runtime settings for this runtime process.
    """
    stopped = Event()
    configure_pywikibot()
    shutdown_reason = "HTTP loop ended"
    control = {"drain": False}

    def stop(signum: int, _frame: FrameType | None) -> None:
        """Request graceful shutdown from the process's main thread."""
        nonlocal shutdown_reason
        if signum == signal.SIGUSR1:
            control["drain"] = True
            return
        shutdown_reason = signal.Signals(signum).name
        stopped.set()

    with ExitStack() as resources:
        resources.enter_context(open_run_log(config.log_dir))
        _LOGGER.info(
            "Aranami %s runtime hub started.",
            project_version(),
            extra=event_extra(
                "service_started",
                service="hub",
                dry=config.dry,
            ),
        )
        resources.callback(
            _LOGGER.info,
            "Aranami %s runtime hub stopped.",
            project_version(),
            extra=event_extra(
                "service_stopped",
                service="hub",
                dry=config.dry,
            ),
        )
        for kind in (signal.SIGINT, signal.SIGTERM, signal.SIGUSR1):
            previous = signal.signal(kind, stop)
            resources.callback(signal.signal, kind, previous)

        updater = None
        server = None
        if not config.dry:
            updater = dashboard_updater(
                config.output,
                days=config.days,
                log_dir=config.log_dir,
                refresh_intervals=config.refresh_intervals,
            )
            server = resources.enter_context(
                DashboardHTTPServer((config.host, config.port), updater),
            )
            server.timeout = 0.25
            updater.start()
            resources.callback(updater.stop)
            refresh_saved_repairs(config.output)

        scheduler = monitor.start(
            dry=config.dry,
            run_immediately=config.run_immediately,
            start_paused=True,
        )
        resources.callback(stop_jobs, scheduler, updater)
        if updater is not None:
            _schedule_collections(scheduler, updater, config)
        scheduler.resume()
        try:
            _serve_until_stopped(
                server,
                scheduler,
                updater,
                stopped,
                control,
            )
        except KeyboardInterrupt:
            shutdown_reason = "KeyboardInterrupt"
            stopped.set()
        finally:
            _LOGGER.info(
                "Aranami runtime hub stopping (%s); waiting for active work.",
                shutdown_reason,
                extra=event_extra(
                    "service_stopping",
                    service="hub",
                    dry=config.dry,
                ),
            )


def main(argv: Sequence[str] | None = None) -> None:
    """Parse runtime options and run the shared runtime hub.

    Args:
        argv: Explicit command-line arguments, or the process arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Write wiki previews without refreshing production website data.",
    )
    parser.add_argument(
        "--run-immediately",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Check outputs immediately before following their schedules.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    parser.add_argument(
        "--interval",
        type=float,
        default=_WEBSITE_CHECK_SECONDS,
    )
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    add_refresh_arguments(parser)
    arguments = parser.parse_args(argv)
    try:
        config = HubConfig(
            dry=arguments.dry,
            run_immediately=arguments.run_immediately,
            output=arguments.output,
            log_dir=arguments.log_dir,
            interval=arguments.interval,
            days=arguments.days,
            host=arguments.host,
            port=arguments.port,
            refresh_intervals=refresh_arguments(arguments),
        )
    except ValueError as error:
        parser.error(str(error))
    run(config)
