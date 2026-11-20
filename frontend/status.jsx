/** Render saved service, report and dataset update observations. */
import { jsx, iconHref, attribute, clockAttributes, display, format, hasContent } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { popup, TablePager, Time } from "./shared.jsx";

export function instant(context, stamp) {
    const { t } = context;
    return hasContent(stamp) && hasContent(stamp?.known) ? (
        <>
            {Time({ ...context, stamp: stamp, time: stamp })}
            {" UTC"}
        </>
    ) : (
        t.data.unknown
    );
}

export function baseline(context, item) {
    const { t } = context;
    return (
        <>
            {t.dataset_updates.baseline}{" "}
            {hasContent(item?.baseline) ? (
                <>
                    {hasContent(item?.baseline?.url) ? (
                        <a href={attribute(item?.baseline?.url)} data-dataset-link={""}>
                            {display(item?.baseline?.filename)}
                        </a>
                    ) : (
                        display(item?.baseline?.filename)
                    )}
                </>
            ) : (
                t.data.unknown
            )}
        </>
    );
}

export function consumers(context, item) {
    const { t } = context;
    return (
        <li>
            {t.dataset_updates.used_by}
            {hasContent(item?.reports) ? (
                <ul>
                    {(item?.reports ?? []).map((report, reportIndex) => (
                        <li key={reportIndex}>
                            {hasContent(report?.url) ? (
                                <a href={attribute(report?.url)}>{display(report?.name)}</a>
                            ) : (
                                display(report?.name)
                            )}
                        </li>
                    ))}
                </ul>
            ) : (
                <div class="dataset-update-note">{t.dataset_updates.no_reports}</div>
            )}
        </li>
    );
}

export function DatasetUpdates(context) {
    const { server, t } = context;
    return ((updates) =>
        ((previous) =>
            ((current) => (
                <>
                    <section
                        id="dataset-updates-current"
                        class="dataset-updates"
                        aria-labelledby="dataset-updates-current-heading"
                    >
                        <h2 id="dataset-updates-current-heading">
                            {display(t.dataset_updates.schedule)}
                        </h2>
                        <div>
                            {hasContent(current?.["items"] ?? []) ? (
                                <ul class="dataset-update-files">
                                    {(current?.["items"] ?? [] ?? []).map((item, itemIndex) => (
                                        <li
                                            key={itemIndex}
                                            data-key={attribute(item?.key ?? item?.filename)}
                                        >
                                            <p>
                                                <span
                                                    role="img"
                                                    aria-label={attribute(
                                                        item?.state === "running"
                                                            ? t.dataset_updates.running
                                                            : hasContent(item?.scheduled) &&
                                                                hasContent(item?.scheduled?.known)
                                                              ? t.dataset_updates.scheduled
                                                              : t.dataset_updates.waiting,
                                                    )}
                                                >
                                                    {"⌛"}
                                                </span>{" "}
                                                <strong>{display(item?.filename)}</strong>
                                            </p>
                                            <ul class="dataset-update-details">
                                                <li>
                                                    {hasContent(item?.started) &&
                                                    hasContent(item?.started?.known) ? (
                                                        <>
                                                            {display(t.dataset_updates.started)}{" "}
                                                            {instant(context, item?.started)}
                                                        </>
                                                    ) : hasContent(item?.scheduled) &&
                                                      hasContent(item?.scheduled?.known) ? (
                                                        <>
                                                            {display(t.dataset_updates.scheduled)}{" "}
                                                            {instant(context, item?.scheduled)}
                                                        </>
                                                    ) : (
                                                        display(t.dataset_updates.waiting)
                                                    )}
                                                    {!hasContent(item?.is_task) ? (
                                                        <>
                                                            {"; "}
                                                            {baseline(context, item)}
                                                        </>
                                                    ) : null}
                                                </li>
                                                {hasContent(item?.elapsed) &&
                                                hasContent(item?.elapsed?.running) ? (
                                                    <li>
                                                        {display(t.dataset_updates.elapsed)}{" "}
                                                        <span
                                                            data-clock="dataset-elapsed"
                                                            data-started-at={attribute(
                                                                item?.elapsed?.started,
                                                            )}
                                                            {...(hasContent(updates?.expires)
                                                                ? {
                                                                      "data-clock-expires": attribute(
                                                                          updates?.expires,
                                                                      ),
                                                                  }
                                                                : {})}
                                                            data-clock-unknown={attribute(
                                                                t.data.unknown,
                                                            )}
                                                        >
                                                            {display(item?.elapsed?.label)}
                                                        </span>
                                                        {hasContent(item?.activity) ? (
                                                            <>
                                                                {" · "}
                                                                {display(item?.activity)}
                                                            </>
                                                        ) : null}
                                                    </li>
                                                ) : hasContent(item?.activity) ? (
                                                    <li>{display(item?.activity)}</li>
                                                ) : null}
                                                {!hasContent(item?.is_task)
                                                    ? consumers(context, item)
                                                    : null}
                                            </ul>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p class="context">
                                    {display(
                                        current?.state === "unavailable"
                                            ? t.dataset_updates.unavailable
                                            : t.dataset_updates.no_planned,
                                    )}
                                </p>
                            )}
                        </div>
                    </section>
                    <section
                        id="dataset-updates-previous"
                        class="dataset-updates"
                        aria-labelledby="dataset-updates-previous-heading"
                        data-live-key={attribute(previous?.key ?? "")}
                    >
                        <h2 id="dataset-updates-previous-heading">
                            {display(t.dataset_updates.previous)}
                        </h2>
                        {hasContent(previous?.["items"] ?? []) ? (
                            <ul class="dataset-update-files">
                                {(previous?.["items"] ?? [] ?? []).map((item, itemIndex) => (
                                    <li
                                        key={itemIndex}
                                        data-key={attribute(item?.key ?? item?.filename)}
                                    >
                                        <p>
                                            <span
                                                role="img"
                                                aria-label={attribute(
                                                    item?.state === "succeeded"
                                                        ? t.dataset_updates.succeeded
                                                        : item?.state === "failed"
                                                          ? t.dataset_updates.failed
                                                          : t.data.unknown,
                                                )}
                                            >
                                                {display(
                                                    item?.state === "succeeded"
                                                        ? "✅"
                                                        : item?.state === "failed"
                                                          ? "❌"
                                                          : "?",
                                                )}
                                            </span>{" "}
                                            <strong>
                                                {hasContent(item?.url) ? (
                                                    <a
                                                        href={attribute(item?.url)}
                                                        data-dataset-link={""}
                                                    >
                                                        {display(item?.filename)}
                                                    </a>
                                                ) : (
                                                    display(item?.filename)
                                                )}
                                            </strong>
                                        </p>
                                        <ul class="dataset-update-details">
                                            <li>
                                                {display(t.dataset_updates.started)}{" "}
                                                {instant(context, item?.started)}
                                                <div class="dataset-update-note">{baseline(context, item)}</div>
                                            </li>
                                            <li>
                                                {t.dataset_updates.finished}{" "}
                                                {instant(context, item?.finished)}
                                                {hasContent(item?.shape) ? (
                                                    <div class="dataset-update-note dataset-update-shape">
                                                        {display(item?.shape)}
                                                    </div>
                                                ) : null}
                                            </li>
                                            {consumers(context, item)}
                                        </ul>
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <p class="context">{display(t.dataset_updates.no_previous)}</p>
                        )}
                    </section>
                </>
            ))(updates?.current ?? {}))(updates?.previous ?? {}))(server?.dataset_updates ?? {});
}

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

/** Present each service in its own column of the metrics table. */
export function Runtime(context) {
    const { server, t } = context;
    return (
        <div id="server-runtime" class="ui-table">
            <div class="ui-table__table-wrapper">
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
