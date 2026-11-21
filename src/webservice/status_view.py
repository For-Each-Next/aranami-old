"""Localize independent runtime observations.

Pass a validated envelope to ``status_context``. The presentation does
not infer a successful task or publication from another domain.
"""

from __future__ import annotations

import datetime as dt
import operator
from typing import TYPE_CHECKING

from shared.config import PAGEVIEWS_START_HOUR
from shared.toolforge.jobs import (
    ON_DEMAND,
    PAGEVIEWS,
    PAGEVIEWS_CHECK_CRON,
    job_name,
)
from webservice.dataset_updates import (
    dataset_updates_context,
    native_executions,
)
from webservice.job_history import (
    REPORTS_PAGE_SIZE,
    history_context,
    source_description,
)
from webservice.presentation import (
    catalog,
    duration,
    failure_description,
    grouped_number,
    job_schedule,
    readable_size,
    timestamp,
    title_url,
    utc_time,
    wiki_link,
)

if TYPE_CHECKING:
    from webservice.presentation import Interface, Record


def observed_time(value: object) -> Record:
    """Prepare a known UTC timestamp or its unknown marker.

    Returns:
        Original instant, display label, and availability.
    """
    label = utc_time(value, seconds=True)
    return {"value": value, "label": label, "known": label != "—"}


def task_name(interface: Interface, identifier: str) -> str:
    """Localize a known task name.

    Returns:
        Authored text or the unfamiliar identifier unchanged.
    """
    key = f"routine.{identifier}"
    return interface.text(key) if key in catalog() else identifier


def _state(interface: Interface, domain: str, value: str) -> str:
    return interface.text(f"observability.{domain}.{value}")


def _services(interface: Interface, status: Record) -> list[Record]:
    """Separate lifecycle and heartbeat freshness.

    Returns:
        Service rows with their independently observed schedules.
    """
    rows = []
    for item in status.get("services", {}).values():
        schedules = item.get("schedules", {})
        rows.append({
            "name": interface.text(
                f"observability.service_name.{item['service_id']}",
            )
            if f"observability.service_name.{item['service_id']}" in catalog()
            else item["service_id"],
            "state": _state(interface, "service", item["lifecycle"]),
            "freshness": _state(interface, "freshness", item["freshness"]),
            "fresh": item["freshness"] == "current",
            "expires": (
                timestamp(item["heartbeat_at"]) + dt.timedelta(seconds=90)
            ).isoformat()
            if item["freshness"] == "current"
            and item["lifecycle"] != "stopped"
            else None,
            "observed": observed_time(item.get("heartbeat_at")),
            "started": observed_time(item.get("started_at")),
            "scheduled": [
                {
                    "name": task_name(interface, name),
                    "next": observed_time(
                        task.get("next_run_at")
                        if item["freshness"] == "current"
                        and item["lifecycle"] == "running"
                        and task.get("state") == "scheduled"
                        else None,
                    ),
                }
                for group in schedules.values()
                for name, task in group.items()
            ],
        })
    return rows


def _datasets(interface: Interface, status: Record) -> list[Record]:
    """Describe accepted datasets using their own observations.

    Returns:
        Dataset freshness, observation, storage, and coverage rows.
    """
    return [
        {
            "id": row["dataset_id"],
            "name": task_name(interface, row["name"]),
            "scope": " / ".join(
                filter(None, (row.get("site"), row.get("project"))),
            ),
            "state": _state(interface, "freshness", row["freshness"]),
            "observed": observed_time(row.get("observed_at")),
            "committed": observed_time(row.get("committed_at")),
            "coverage": " \u2013 ".join(
                interface.date(value)
                for value in dict.fromkeys((
                    row.get("coverage_start"),
                    row.get("coverage_end"),
                ))
                if value
            )
            or interface.text("ops.unavailable"),
            "generation": row.get("generation"),
        }
        for row in status.get("datasets", {}).values()
    ]


def _publications(interface: Interface, status: Record) -> list[Record]:
    """Show independent publication attempts and confirmed saves.

    Returns:
        Destination rows with revision links only for confirmed saves.
    """
    rows = []
    for record in status.get("publications", {}).values():
        outcome = _state(interface, "publication", record["outcome"])
        url = title_url(record["title"], record["site"])
        if record["outcome"] == "saved" and record.get("revision_id"):
            outcome = wiki_link(
                url + "?oldid=" + str(record["revision_id"]),
                outcome,
            )
        rows.append({
            "task_id": record["task_id"],
            "title": record["title"],
            "target": wiki_link(url, record["title"]),
            "result": outcome,
            "started": observed_time(record.get("started_at")),
            "saved": observed_time(record.get("last_confirmed_save_at")),
            "duration": duration(record.get("duration_seconds"), interface),
        })
    return rows


def _report_schedule(
    interface: Interface,
    service: Record,
    identifier: str,
    configured_at: str | None = None,
) -> Record:
    """Describe observed scheduler times and configured launches.

    Returns:
        Next observed check or the reason that its time is unavailable.
    """
    if configured_at:
        return {
            "time": observed_time(configured_at),
            "label": interface.text("ops.schedule_configured"),
            "expires": configured_at,
        }
    schedule = (
        service
        .get("schedules", {})
        .get("routines", {})
        .get(
            identifier,
            {},
        )
    )
    next_at = None
    state = "missing"
    if service and service.get("freshness") != "current":
        state = "stale"
    elif service.get("lifecycle") in {"stopped", "draining"}:
        state = "stopped"
    elif service.get("lifecycle") == "paused":
        state = "paused"
    elif service.get("lifecycle") == "running":
        state = schedule.get("state", "missing")
        if schedule.get("queued_since"):
            state = "idle"
        elif state == "scheduled":
            next_at = schedule.get("next_run_at")
    return {
        "time": observed_time(next_at),
        "label": interface.text(
            f"ops.schedule_{state if state != 'scheduled' else 'missing'}",
        ),
        "expires": (
            timestamp(service["heartbeat_at"]) + dt.timedelta(seconds=90)
        ).isoformat()
        if next_at
        else None,
    }


def _report_coverage(
    interface: Interface,
    identifier: str,
    runs: list[Record],
) -> str | None:
    """Describe the latest completed check independently of wiki edits.

    Args:
        interface: Selected language for report status text.
        identifier: Configured report routine.
        runs: Retained executions belonging to this routine.

    Returns:
        Confirmed daily report date or completed hourly check, when
        one is available. Later failures do not erase earlier coverage.
    """
    completed = [run for run in runs if run["outcome"] == "succeeded"]
    if identifier == "dyks":
        finished = [
            timestamp(run.get("finished_at"))
            for run in completed
            if timestamp(run.get("finished_at")) is not None
        ]
        if not finished:
            return None
        instant = max(finished)
        return interface.text(
            "reports.updated_hourly",
            date=interface.date(instant.date().isoformat()),
            hour=f"{instant.hour:02d}:00 UTC"
            if interface.locale == "en"
            else instant.hour,
        )
    days = [run["report_date"] for run in runs if run.get("report_date")]
    return (
        interface.text("reports.updated_daily", date=interface.date(max(days)))
        if days
        else None
    )


def _report_activity(
    interface: Interface,
    run: Record,
) -> str:
    """Describe only the current phase recorded by an active execution.

    Args:
        interface: Selected language for activity text.
        run: Active execution and its recorded progress or stages.

    Returns:
        A localized current action with any known progress counters.
    """
    progress = run.get("progress") or {}
    phase = progress.get("phase")
    source = progress.get("source")
    if not phase:
        stages = run.get("stages", [])
        phase = stages[-1]["kind"] if stages else "started"
        source = stages[-1].get("source") if stages else None
    key = f"reports.running.{phase}"
    activity = (
        source_description(source, interface, kind=phase, links=False)
        if source
        and phase
        in {
            "source_read",
            "source_loaded",
            "source_written",
            "source_unchanged",
            "checking",
            "saving",
        }
        else interface.text(
            "reports.running.fetching"
            if phase == "source_read"
            else key
            if key in catalog()
            else "reports.running.started",
            scope="",
        )
    )
    current, total = progress.get("current"), progress.get("total")
    return (
        interface.text(
            "progress.count",
            phase=activity.rstrip(".。…"),
            current=grouped_number(current),
            total=grouped_number(total),
        )
        if current is not None and total is not None
        else activity
    )


def _deferred_status(interface: Interface, run: Record) -> str:
    """Describe an observed deferred date independently of coverage.

    Returns:
        Deferred result with its known attempted date and safe cause.
    """
    failure = run.get("failure") or {}
    day = failure.get("failure_date")
    label = (
        interface.text("reports.deferred_date", date=interface.date(day))
        if day
        else _state(interface, "execution", "deferred")
    )
    reason = failure_description(failure, interface)
    return (
        interface.text("reports.deferred_reason", result=label, reason=reason)
        if reason
        else label
    )


def report_context(  # ruff: ignore[too-many-arguments] - Include native paging controls.
    interface: Interface,
    status: Record,
    definitions: Record,
    now: dt.datetime,
    *,
    history_page: int | None = None,
    history_size: int = REPORTS_PAGE_SIZE,
) -> Record:
    """Group on-wiki reports with independent run and publication facts.

    Args:
        interface: Selected locale and authored messages.
        status: Validated saved runtime observations.
        definitions: Configured on-wiki reports and their destinations.
        now: UTC rendering instant.
        history_page: Requested page. Zero omits history details.
            None retains all history for direct presentation callers.
        history_size: Maximum rows on each requested page.

    Returns:
        Report cards, on-wiki history and their status dialogs.
        Collection tasks never appear in this report-only selection.
    """
    runs = {
        key: run
        for key, run in status.get("executions", {}).items()
        if run["task_id"] in definitions and run["kind"] == "report"
    }
    selected = {**status, "executions": runs}
    history = history_context(
        interface,
        selected,
        now,
        offset=max(0, (history_page or 0) - 1) * history_size,
        limit=None
        if history_page is None
        else history_size
        if history_page
        else 0,
    )
    dialogs = {row["run_id"]: row for row in history["history_dialogs"]}
    publications = _publications(interface, status)
    service = status.get("services", {}).get("scheduler", {})
    rows = []
    icons = {
        "dyks": "lightbulb",
        "new_pages": "article-add",
        "assessment_lists": "article-check",
        "assessment_log": "history",
        "pageviews": "chart-bar",
        "enwp_key_articles": "language",
        "pexbot": "robot",
    }
    for identifier, definition in definitions.items():
        task_runs = [
            row for row in runs.values() if row["task_id"] == identifier
        ]
        run = max(
            task_runs,
            key=operator.itemgetter("started_at"),
            default=None,
        )
        event = None
        if run is not None:
            event = dialogs.get(run["run_id"])
            if event is None:
                event = history_context(
                    interface,
                    {**status, "executions": {run["run_id"]: run}},
                    now,
                    recent_only=False,
                )["events"][0]
        targets = list(definition.get("pages", {}).values())
        if not targets:
            targets = definition.get("prefixes", [])
        attempts = [
            row for row in publications if row["task_id"] == identifier
        ]
        saves = [
            row["saved"]["value"] for row in attempts if row["saved"]["known"]
        ]
        coverage = _report_coverage(interface, identifier, task_runs)
        rows.append({
            "identifier": identifier,
            "name": task_name(interface, identifier),
            "icon": icons.get(identifier, "article"),
            "targets": [
                wiki_link(
                    title_url(title),
                    chr(ord("a") + index)
                    if len(targets) > 1
                    else task_name(interface, identifier),
                    title,
                )
                for index, title in enumerate(targets)
            ],
            "event": event,
            "coverage": coverage,
            "status": _report_activity(interface, run)
            if run and run["outcome"] == "running"
            else _deferred_status(interface, run)
            if run and run["outcome"] == "deferred"
            else coverage
            if run and run["outcome"] == "succeeded" and coverage
            else interface.text(
                "reports.failed_task",
                task=task_name(interface, identifier),
            )
            if run and run["outcome"] == "failed"
            else event["result"]
            if event
            else interface.text("ops.no_record"),
            "opening": " (" if interface.locale == "en" else "\uff08",
            "closing": ")" if interface.locale == "en" else "\uff09",
            "observed": observed_time(
                run["started_at"]
                if run and run["outcome"] == "running"
                else run.get("finished_at")
                if run
                else None,
            ),
            "running": run is not None and run["outcome"] == "running",
            "deferred": run is not None and run["outcome"] == "deferred",
            "schedule": _report_schedule(
                interface,
                service,
                identifier,
                status
                .get("toolforge_schedules", {})
                .get("routines", {})
                .get(identifier, {})
                .get("next_run_at"),
            ),
            "saved": observed_time(
                max(saves, key=timestamp) if saves else None,
            ),
            "publications": attempts,
            "popup_id": f"report-details-{identifier}",
            "popup_heading": interface.text(
                "ops.details",
                routine=task_name(interface, identifier),
            ),
        })
    return {
        "routines": rows,
        "events": history["events"],
        "history_dialogs": list(dialogs.values()),
        "history_total": history["history_total"],
        "history_offset": history["history_offset"],
    }


def _service_expiry(service: Record) -> str | None:
    """Return the expiration for an active service's current heartbeat.

    Returns:
        The UTC deadline, or none for unavailable or terminal health.
    """
    heartbeat = timestamp(service.get("heartbeat_at"))
    if (
        heartbeat
        and service.get("freshness") == "current"
        and service.get("lifecycle") != "stopped"
    ):
        return (heartbeat + dt.timedelta(seconds=90)).isoformat()
    return None


def _core_label(interface: Interface, cores: float) -> str:
    """Format an observed CPU count without losing small fractions.

    Returns:
        A localized CPU usage or allocation label.
    """
    count = f"{cores:.3f}".rstrip("0").rstrip(".")
    return interface.text(
        "server.cpu_core" if count == "1" else "server.cpu_cores",
        count=count,
    )


def _job_usage(
    interface: Interface,
    resources: Record,
    limits: Record,
) -> Record:
    """Format memory and CPU against the job allocation.

    Returns:
        Usage and limit labels with explicit unknown values.
    """
    unknown = interface.text("data.unknown")
    used = resources.get("memory_bytes")
    memory = resources.get("memory_limit_bytes") or limits.get(
        "memory_limit_bytes",
    )
    cpu_percent = resources.get("cpu_percent")
    cpu = resources.get("cpu_limit") or limits.get("cpu_limit")
    cpu_use = (
        _core_label(interface, cpu_percent / 100)
        if cpu_percent is not None
        else unknown
    )
    cpu_cap = _core_label(interface, cpu) if cpu is not None else unknown
    return {
        "memory": (
            f"{readable_size(used) if used is not None else unknown}"
            f" / {readable_size(memory) if memory is not None else unknown}"
        ),
        "cpu": f"{cpu_use} / {cpu_cap}",
    }


def _job_state(
    interface: Interface,
    now: dt.datetime,
    outcome: str,
    since: str | None,
) -> str:
    """Localize the current lifecycle with elapsed time when observed.

    Returns:
        Human-readable lifecycle for the Toolforge status table.
    """
    if outcome in {"running", "pending"} and (instant := timestamp(since)):
        elapsed = duration(
            max(0, (now - instant).total_seconds()),
            interface,
            running=True,
        ).removesuffix("…")
        return interface.text(f"server.job_{outcome}_for", duration=elapsed)
    return interface.text(f"server.job_{outcome}")


def _scheduled_job_row(
    interface: Interface,
    now: dt.datetime,
    schedule: Record,
    execution: Record,
    sample: Record,
) -> Record:
    """Present the latest observed run beside the job's real allocation.

    Returns:
        A row for one installed CronJob.
    """
    observed = timestamp(sample.get("observed_at"))
    execution_at = timestamp(
        execution.get("finished_at")
        or execution.get("detected_at")
        or execution.get("started_at"),
    )
    expiry = None
    resources = {}
    outcome = "pending"
    since = None
    if observed and (execution_at is None or execution_at <= observed):
        outcome = sample["outcome"]
        since = sample["started_at"]
        if outcome == "succeeded":
            since = sample["observed_at"]
        elif outcome == "running":
            expires = timestamp(sample["expires_at"])
            if expires and now < expires:
                resources = sample["resources"]
                expiry = sample["expires_at"]
            else:
                outcome = "unknown"
    elif execution_at is not None:
        outcome = execution["outcome"]
        since = (
            execution.get("finished_at")
            if outcome == "succeeded"
            else execution["started_at"]
        )
        heartbeat = timestamp(execution.get("updated_at"))
        if outcome == "running":
            expires = (
                heartbeat + dt.timedelta(seconds=90) if heartbeat else None
            )
            if expires and now < expires:
                expiry = expires.isoformat()
            else:
                outcome = "unknown"
    cron = schedule["cron"]
    if outcome == "succeeded" and cron is not None:
        outcome = "pending"
    if schedule["state"] == "paused" and outcome != "running":
        outcome = "paused"
    return {
        "key": schedule["job_name"],
        "type": job_schedule(interface, schedule)
        if cron is not None
        else interface.text("server.job_one_off"),
        "cron": cron,
        "status": _job_state(interface, now, outcome, since),
        "expires": expiry,
        "usage": _job_usage(interface, resources, schedule),
        "idle_usage": _job_usage(interface, {}, schedule),
    }


def _toolforge_schedule_order(
    item: tuple[str, Record],
) -> tuple[int, int, int, str]:
    """Order daily, hourly, weekly and on-demand jobs by schedule.

    Returns:
        The schedule group, hour, minute and stable job name.
    """
    task, schedule = item
    name = schedule["job_name"]
    cron = schedule["cron"]
    if cron is None:
        return 3, 0, 0, name
    if task == PAGEVIEWS and cron == PAGEVIEWS_CHECK_CRON:
        return 0, PAGEVIEWS_START_HOUR, 0, name
    fields = cron.split()
    if (
        len(fields) == 5  # ruff: ignore[magic-value-comparison] - Cron fields.
        and fields[2:] == ["*", "*", "*"]
        and fields[0].isdigit()
    ):
        minute, hour = fields[:2]
        if hour.isdigit():
            return 0, int(hour), int(minute), name
        if hour == "*":
            return 1, 0, int(minute), name
    return 2, 0, 0, name


def _toolforge_rows(
    interface: Interface,
    status: Record,
    now: dt.datetime,
) -> list[Record]:
    """Build the continuous and scheduled workload status table.

    Returns:
        The web job followed by installed collection and report jobs.
    """
    web = status.get("services", {}).get("web", {})
    expiry = _service_expiry(web)
    resources = web.get("resources") or {}
    rows = [
        {
            "key": "aranami-web",
            "name": interface.text("server.web_service"),
            "type": interface.text("server.job_continuous"),
            "status": _job_state(
                interface,
                now,
                "running"
                if expiry and web.get("lifecycle") == "running"
                else "unknown",
                web.get("started_at"),
            ),
            "expires": expiry,
            "usage": _job_usage(
                interface,
                resources if expiry else {},
                resources,
            ),
            "idle_usage": _job_usage(interface, {}, resources),
        },
    ]
    if not (plan := status.get("toolforge_schedules")):
        return rows

    executions = {}
    for run in sorted(
        native_executions(status),
        key=operator.itemgetter("started_at"),
    ):
        executions[run["task_id"]] = run
    samples = status.get("toolforge_samples", {})
    schedules = plan.get("services", plan["collections"] | plan["routines"])
    if "services" in plan:
        schedules = {
            **schedules,
            **{
                task: {
                    "job_name": job_name(task),
                    "cron": None,
                    "state": "manual",
                    "memory_limit_bytes": int(
                        ON_DEMAND[task]["mem"].removesuffix("Mi"),
                    )
                    * 1024**2,
                    "cpu_limit": ON_DEMAND[task]["cpu"],
                }
                for task in ON_DEMAND
                if task not in schedules and task in samples
            },
        }
    for task, schedule in sorted(
        schedules.items(),
        key=_toolforge_schedule_order,
    ):
        rows.append({
            **_scheduled_job_row(
                interface,
                now,
                schedule,
                executions.get(task, {}),
                samples.get(task, {}),
            ),
            "name": task_name(interface, task),
        })
    return rows


def status_context(
    interface: Interface,
    status: Record,
    version: str,
    now: dt.datetime,
    *,
    history_limit: int | None = None,
) -> Record:
    """Present a validated status envelope with explicit missing facts.

    Args:
        interface: Selected locale and authored messages.
        status: Version-one saved observations read by the data layer.
        version: Running web source version.
        now: UTC rendering instant.
        history_limit: Optional bound on localized execution details;
            zero omits them and none preserves the complete direct view.

    Returns:
        Independent runtime domains and shared footer contexts.
    """
    services = _services(interface, status)
    web = status.get("services", {}).get("web", {})
    expires = _service_expiry(web)
    started = web.get("started_at") if expires else None
    instant = timestamp(started)
    footer_unknown = interface.text("footer.uptime_unknown", version=version)
    footer_label = (
        interface.text(
            "footer.uptime",
            version=version,
            duration=duration(
                max(0, int((now - instant).total_seconds())),
                interface,
                running=True,
            ).removesuffix("…"),
            since=utc_time(started),
        )
        if instant
        else footer_unknown
    )
    return {
        **history_context(interface, status, now, limit=history_limit),
        "status_availability": _state(
            interface,
            "availability",
            status.get("availability", "missing"),
        ),
        "status_available": status.get("availability") == "available",
        "services": services,
        "datasets": _datasets(interface, status),
        "publications": _publications(interface, status),
        "clock_expires": expires,
        "footer": {
            "label": footer_label,
            "started": started,
            "template": interface.text(
                "footer.uptime",
                version=version,
                duration=interface.text(
                    "duration.days",
                    days="{days}",
                    hours="{hours}",
                    minutes="{minutes}",
                    seconds="{seconds}",
                ),
                since=utc_time(started),
            )
            if started
            else None,
            "compact_template": interface.text(
                "footer.uptime",
                version=version,
                duration="{duration}",
                since=utc_time(started),
            )
            if started
            else None,
            "unknown": footer_unknown,
        },
        "server": {
            "dataset_updates": dataset_updates_context(interface, status, now),
            "jobs": _toolforge_rows(interface, status, now),
        },
    }
