/** Render saved service, report and dataset update observations. */
import { jsx, iconHref, attribute, clockAttributes, display, format, hasContent } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { popup, TablePager, Time } from "./shared.jsx";

export function ExecutionDuration(context) {
    const { event } = context;
    return (
        <span
            {...(hasContent(event?.timer_start)
                ? {
                      "data-clock": "elapsed",
                      "data-started-at": attribute(event?.timer_start),
                      "data-clock-expires": attribute(event?.timer_expires),
                      "data-clock-unknown": "—",
                      "data-duration-template": "{duration}",
                  }
                : {})}
        >
            {display(event?.duration)}
        </span>
    );
}

export function JobHistoryDialogs(context) {
    const { history_dialogs, t } = context;
    return (history_dialogs ?? []).map((event, eventIndex) => (
        <Fragment key={eventIndex}>
            {popup(
                context,
                <>
                    <p>
                        {display(event?.result)}
                        {": "}
                        {ExecutionDuration({
                            ...context,
                            event: event,
                        })}
                    </p>
                    {hasContent(event?.progress) ? <p>{display(event?.progress)}</p> : null}
                    {hasContent(event?.attempted_date) ? (
                        <p>
                            {display(
                                format(t.reports.deferred_date, {
                                    date: event?.attempted_date,
                                }),
                            )}
                        </p>
                    ) : null}
                    {hasContent(event?.failure) ? <p>{display(event?.failure)}</p> : null}
                    {hasContent(event?.truncated) ? (
                        <p class="context">{t.reports.stage_truncated}</p>
                    ) : null}
                    <ul class="job-stages">
                        {(event?.stages ?? []).map((stage, stageIndex) => (
                            <li key={stageIndex}>
                                {Time({
                                    ...context,
                                    event: event,
                                    stage: stage,
                                    time: stage?.time,
                                })}{" "}
                                {display(stage?.label)}
                            </li>
                        ))}
                    </ul>
                </>,
                event?.popup_id,
                event?.task,
                "#recent-events",
            )}
        </Fragment>
    ));
}

export function Relative(context) {
    const { relative } = context;
    return hasContent(relative?.label) ? display(relative?.label) : null;
}

export function ReportDetails(context) {
    const { routine, t } = context;
    return popup(
        context,
        <>
            {hasContent(routine?.event) ? (
                <>
                    <p>
                        {t.reports.latest_run} {display(routine?.event?.result)}
                        {": "}
                        {ExecutionDuration({
                            ...context,
                            event: routine?.event,
                        })}
                    </p>
                    {hasContent(routine?.event?.progress) ? (
                        <p>{display(routine?.event?.progress)}</p>
                    ) : null}
                </>
            ) : (
                <p class="context">{t.ops.no_record}</p>
            )}
            {hasContent(routine?.deferred) ? <p>{display(routine?.status)}</p> : null}
            {hasContent(routine?.publications) ? (
                <div class="ui-table">
                    <div
                        class="ui-table__table-wrapper table-scroll"
                        tabindex="0"
                        role="region"
                        aria-label={attribute(routine?.popup_heading)}
                    >
                        <table class="ui-table__table publication-table">
                            <caption class="visually-hidden">{display(routine?.popup_heading)}</caption>
                            <thead>
                                <tr>
                                    <th scope="col">{display(t.observability.target)}</th>
                                    <th scope="col">{t.logs.status}</th>
                                    <th scope="col">{t.logs.started_at}</th>
                                    <th scope="col">{display(t.observability.confirmed_save)}</th>
                                    <th scope="col">{display(t.logs.duration_label)}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {(routine?.publications ?? []).map((publication, publicationIndex) => (
                                    <tr key={publicationIndex}>
                                        <th scope="row">{display(publication?.target)}</th>
                                        <td data-label={attribute(t.logs.status)}>
                                            {display(publication?.result)}
                                        </td>
                                        <td data-label={attribute(t.logs.started_at)}>
                                            {Time({
                                                ...context,
                                                publication: publication,
                                                time: publication?.started,
                                            })}
                                        </td>
                                        <td data-label={attribute(t.observability.confirmed_save)}>
                                            {Time({
                                                ...context,
                                                publication: publication,
                                                time: publication?.saved,
                                            })}
                                        </td>
                                        <td data-label={attribute(t.logs.duration_label)}>
                                            {display(publication?.duration)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            ) : (
                <p class="context">{t.observability.no_publications}</p>
            )}
            {hasContent(routine?.event) ? (
                <>
                    <h4>{t.reports.actions}</h4>
                    {hasContent(routine?.event?.failure) ? (
                        <p>{display(routine?.event?.failure)}</p>
                    ) : null}
                    {hasContent(routine?.event?.truncated) ? (
                        <p class="context">{t.reports.stage_truncated}</p>
                    ) : null}
                    <ul class="job-stages">
                        {(routine?.event?.stages ?? []).map((stage, stageIndex) => (
                            <li key={stageIndex}>
                                {Time({
                                    ...context,
                                    event: routine?.event,
                                    stage: stage,
                                    time: stage?.time,
                                })}{" "}
                                {display(stage?.label)}
                            </li>
                        ))}
                    </ul>
                </>
            ) : null}
        </>,
        routine?.popup_id,
        routine?.popup_heading,
        attribute("#routine-") + attribute(routine?.identifier),
    );
}

export function execution_row(context, event) {
    return (
        <tr data-key={attribute(event?.popup_id)}>
            <td>{Time({ ...context, event: event, time: event?.time })}</td>
            <td>{display(event?.task)}</td>
            <td>
                <a
                    class="status-link"
                    href={"#" + attribute(event?.popup_id)}
                    aria-controls={attribute(event?.popup_id)}
                    aria-haspopup="dialog"
                >
                    {display(event?.result)}
                </a>
            </td>
            <td class="ui-table__table__cell--align-number">
                {ExecutionDuration({ ...context, event: event })}
            </td>
        </tr>
    );
}

export function ReportLog(context) {
    const { events, history_pagination, language_tag, t } = context;
    return (
        <section class="section-flat" aria-labelledby="recent-events">
            <h2 id="recent-events">{t.reports.log}</h2>
            <p class="page-description">{t.reports.history_note}</p>
            {hasContent(events) ? null : <p class="context">{t.reports.empty}</p>}
            <div
                data-execution-history={""}
                data-page={attribute(history_pagination?.page)}
                data-total={attribute(history_pagination?.total)}
            >
                <div class="ui-table">
                    <div
                        class="ui-table__table-wrapper table-scroll"
                        tabindex="0"
                        role="region"
                        aria-label={t.reports.log}
                    >
                        <table class="ui-table__table logs-table">
                            <caption class="visually-hidden">{t.reports.log}</caption>
                            <thead>
                                <tr>
                                    <th scope="col">{t.logs.started_at}</th>
                                    <th scope="col">{t.logs.task_label}</th>
                                    <th scope="col">{t.logs.status}</th>
                                    <th scope="col" class="ui-table__table__cell--align-number">
                                        {display(t.logs.duration_label)}
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {(events ?? []).map((event, eventIndex) => (
                                    <Fragment key={eventIndex}>
                                        {execution_row(context, event)}
                                    </Fragment>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
                <TablePager paging={history_pagination} action="/reports/#recent-events"
                            fields={{ lang: language_tag }} css="history-pagination"
                            title={t.reports.log} t={t} />
            </div>
        </section>
    );
}

export function RoutineCard(context) {
    const { routine, t } = context;
    return (
        <article
            class="ui-card routine-row"
            aria-labelledby={"routine-" + attribute(routine?.identifier) + "-heading"}
            id={"routine-" + attribute(routine?.identifier)}
        >
            <svg
                class="report-icon ui-card__icon"
                viewBox="0 0 20 20"
                aria-hidden="true"
                focusable="false"
            >
                <use href={iconHref(context, routine?.icon)}></use>
            </svg>
            <div class="ui-card__text">
                <div class="ui-card__text__title">
                    <h3 id={"routine-" + attribute(routine?.identifier) + "-heading"}>
                        {(routine?.targets?.length ?? 0) === 1 ? (
                            display(routine?.targets?.[0])
                        ) : (
                            <>
                                {display(routine?.name)}
                                <span class="routine-targets">
                                    {display(routine?.opening)}
                                    {(routine?.targets ?? []).map((target, targetIndex, targetItems) => (
                                        <Fragment key={targetIndex}>
                                            {display(target)}
                                            {!hasContent(targetIndex === targetItems.length - 1) ? (
                                                <> </>
                                            ) : null}
                                        </Fragment>
                                    ))}
                                    {display(routine?.closing)}
                                </span>
                            </>
                        )}
                    </h3>
                </div>
                <div class="ui-card__text__description">
                    <p class="routine-status">
                        <a
                            class="status-link"
                            href={"#" + attribute(routine?.popup_id)}
                            aria-controls={attribute(routine?.popup_id)}
                            aria-haspopup="dialog"
                        >
                            {display(routine?.status)}
                        </a>
                    </p>
                    {hasContent(routine?.coverage) && routine?.status !== routine?.coverage ? (
                        <p class="routine-coverage">{display(routine?.coverage)}</p>
                    ) : null}
                </div>
                <div class="ui-card__text__supporting-text">
                    <dl class="routine-meta">
                        <div>
                            <dt>
                                {display(
                                    hasContent(routine?.running)
                                        ? t.reports.execution_started
                                        : t.reports.last_execution,
                                )}
                            </dt>
                            <dd>
                                {Time({
                                    ...context,
                                    time: routine?.observed,
                                })}
                            </dd>
                        </div>
                        <div>
                            <dt>{t.reports.next_execution}</dt>
                            <dd
                                {...(hasContent(routine?.schedule?.expires)
                                    ? {
                                          "data-observation-expires": attribute(
                                              routine?.schedule?.expires,
                                          ),
                                          "data-stale-text": attribute(t.ops.schedule_stale),
                                      }
                                    : {})}
                            >
                                {hasContent(routine?.schedule?.time?.known)
                                    ? Time({
                                          ...context,
                                          time: routine?.schedule?.time,
                                      })
                                    : display(routine?.schedule?.label)}
                            </dd>
                        </div>
                    </dl>
                </div>
            </div>
            {ReportDetails(context)}
        </article>
    );
}

export function Routines(context) {
    const { routines, status_availability, status_available, t } = context;
    return (
        <div id="tool-status" {...clockAttributes(context.clock)}>
            <p
                id="live-notice"
                class="ui-message ui-message--notice ui-message--inline"
                role="status"
                data-stale-text={t.ops.live_stale}
                data-disconnected-text={t.ops.reconnecting}
                hidden
            >
                {t.ops.reconnecting}
            </p>
            {!hasContent(status_available) ? (
                <p class="ui-message ui-message--notice">{display(status_availability)}</p>
            ) : null}
            <section class="section-flat" aria-labelledby="tool-status-heading">
                <h2 id="tool-status-heading">{t.reports.panel}</h2>
                <div class="routine-rows">
                    {(routines ?? []).map((routine, routineIndex) => (
                        <Fragment key={routineIndex}>
                            {RoutineCard({ ...context, routine: routine })}
                        </Fragment>
                    ))}
                </div>
            </section>
        </div>
    );
}

/** Present each installed job with its current state and container metrics. */
function JobTable({ jobs, t }) {
    return (
        <table class="ui-table__table server-jobs" data-no-pagination="">
            <caption class="visually-hidden">{t.server.heading}</caption>
            <thead>
                <tr>
                    {["job", "job_type", "state", "memory", "cpu"].map(key => (
                        <th scope="col" key={key}>{t.server[key]}</th>
                    ))}
                </tr>
            </thead>
            <tbody>
                {jobs.map(job => (
                    <tr key={job.key} data-key={job.key}>
                        <th scope="row" title={job.name}>{job.key}</th>
                        <td title={job.cron ?? undefined}>{job.type}</td>
                        <td>
                            <span data-observation-expires={job.expires ?? undefined}
                                data-stale-text={job.expires ? t.server.job_unknown : undefined}>
                                {job.status}
                            </span>
                        </td>
                        {["memory", "cpu"].map(metric => (
                            <td key={metric}>
                                <span data-observation-expires={job.expires ?? undefined}
                                    data-stale-text={job.expires ? job.idle_usage[metric] : undefined}>
                                    {job.usage[metric]}
                                </span>
                            </td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

/** Present the job metrics, with the legacy service view for earlier data. */
export function Runtime(context) {
    const { server, t } = context;
    return (
        <div id="server-runtime" class="ui-table">
            <div class="ui-table__table-wrapper table-scroll" tabindex="0"
                role="region" aria-labelledby="server-status-heading">
                {server?.jobs?.length ? <JobTable jobs={server.jobs} t={t} /> : (
                <table class="ui-table__table server-metrics" data-no-pagination="">
                    <caption class="visually-hidden">{t.server.heading}</caption>
                    <colgroup><col /><col /><col /></colgroup>
                    <thead>
                        <tr>
                            <td></td>
                            <th scope="col">{t.server.hub}</th>
                            <th scope="col">{t.server.web}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(server?.rows ?? []).map(row => (
                            <tr key={row.key} data-server-metric={row.key}>
                                <th scope="row">{row.label}</th>
                                {row.cells.map((cell, index) => (
                                    <td key={index}>
                                        {cell.value && (
                                            <span id={row.key === "state" && index === 0 ? "server-state" : undefined}
                                                data-observation-expires={cell.expires ?? undefined}
                                                data-stale-text={cell.stale ?? undefined}>
                                                {cell.value}
                                            </span>
                                        )}
                                        {cell.time && (
                                            <span class={cell.time_label ? "server-start" : undefined}>
                                                {cell.time_label && <>{server.opening}{cell.time_label}</>}
                                                {Time({...context, time: cell.time})}
                                                {cell.time.known && cell.time_relative?.label &&
                                                    <>{cell.time_label ? server.separator : " "}{Relative({...context, relative: cell.time_relative})}</>}
                                                {cell.time_label && server.closing}
                                            </span>
                                        )}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
                )}
            </div>
        </div>
    );
}

export function Server(context) {
    const { t } = context;
    return (
        <section
            data-refresh-interval="1000"
            id="live-server-status"
            aria-labelledby="server-status-heading"
            {...clockAttributes(context.clock)}
        >
            <h2 id="server-status-heading">{t.server.heading}</h2>
            {Runtime(context)}
            <p
                id="live-server-notice"
                class="context"
                role="status"
                data-stale-text={t.ops.live_stale}
                data-disconnected-text={t.ops.reconnecting}
                hidden
            >
                {t.ops.reconnecting}
            </p>
        </section>
    );
}

export function Uptime(context) {
    const { footer } = context;
    return (
        <span
            id="live-uptime"
            {...clockAttributes(context.clock)}
            {...(hasContent(footer?.started)
                ? {
                      "data-clock": "uptime",
                      "data-started-at": attribute(footer?.started),
                      "data-uptime-template": attribute(footer?.template),
                      "data-uptime-compact-template": attribute(footer?.compact_template),
                  }
                : {})}
            data-uptime-unknown={attribute(footer?.unknown)}
        >
            {display(footer?.label)}
        </span>
    );
}
