/** List saved log segments and activity. */
import { jsx, attribute, display, hasContent } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { Time } from "./shared.jsx";

export function LogsContents(context) {
    const { t } = context;
    return (
        <ul>
            <li>
                <a href="#log-activity">{t.logs.activity}</a>
            </li>
            <li>
                <a href="#log-archive">{t.logs.archive}</a>
            </li>
        </ul>
    );
}

export function Logs(context) {
    const {
        activity,
        files,
        language_tag,
        log_availability,
        log_truncated,
        query,
        run_id,
        selected_date,
        t,
    } = context;
    return (
        <>
            <section class="section-flat" aria-labelledby="log-activity">
                <h2 id="log-activity">{t.logs.activity}</h2>
                <p class="page-description">{t.logs.activity_note}</p>
                <form class="log-filters" method="get" action="/logs/">
                    <input type="hidden" name="lang" value={attribute(language_tag)} />
                    <label>
                        {t.logs.column_date}{" "}
                        <input
                            class="ui-text-input__input"
                            type="date"
                            name="date"
                            required
                            value={attribute(selected_date)}
                        />
                    </label>
                    <label>
                        {t.logs.run_id}{" "}
                        <input
                            class="ui-text-input__input"
                            name="run_id"
                            value={attribute(run_id)}
                            pattern="[0-9a-f]{32}"
                            maxlength="32"
                        />
                    </label>
                    <label>
                        {t.logs.query}{" "}
                        <input
                            class="ui-text-input__input"
                            type="search"
                            name="q"
                            value={attribute(query)}
                            maxlength="256"
                        />
                    </label>
                    <button
                        class="ui-button ui-button--action-progressive ui-button--weight-primary"
                        type="submit"
                    >
                        {t.logs.apply}
                    </button>
                </form>
                {log_availability === "unreadable" ? (
                    <p class="ui-message ui-message--warning" role="status">
                        {t.logs.partial}
                    </p>
                ) : log_availability === "missing" ? (
                    <p class="context">{t.logs.missing}</p>
                ) : null}
                {hasContent(activity) ? (
                    <div class="ui-table">
                        <div
                            class="ui-table__table-wrapper table-scroll"
                            tabindex="0"
                            role="region"
                            aria-label={t.logs.activity}
                        >
                            <table class="ui-table__table logs-table">
                                <thead>
                                    <tr>
                                        <th scope="col">{t.logs.column_date}</th>
                                        <th scope="col">{t.logs.level}</th>
                                        <th scope="col">{t.logs.event}</th>
                                        <th scope="col">{t.logs.details}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(activity ?? []).map((event, eventIndex) => (
                                        <tr key={eventIndex}>
                                            <td>
                                                {Time({
                                                    ...context,
                                                    event: event,
                                                    time: event?.time,
                                                })}
                                            </td>
                                            <td>{display(event?.level)}</td>
                                            <th scope="row">{display(event?.kind)}</th>
                                            <td>
                                                <details>
                                                    <summary>{display(t.logs.details)}</summary>
                                                    <dl class="log-fields">
                                                        {(event?.fields ?? []).map(
                                                            ([key, value], keyIndex) => (
                                                                <Fragment key={keyIndex}>
                                                                    <dt>{display(key)}</dt>
                                                                    <dd>{display(value)}</dd>
                                                                </Fragment>
                                                            ),
                                                        )}
                                                    </dl>
                                                </details>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ) : log_availability === "available" ? (
                    <p class="context">{t.logs.no_events}</p>
                ) : null}
                {hasContent(log_truncated) ? <p class="context">{t.logs.truncated}</p> : null}
            </section>
            <section class="section-flat" aria-labelledby="log-archive">
                <h2 id="log-archive">{t.logs.archive}</h2>
                {hasContent(files) ? (
                    <div class="ui-table">
                        <div
                            class="ui-table__table-wrapper table-scroll"
                            tabindex="0"
                            role="region"
                            aria-label={t.logs.archive}
                        >
                            <table class="ui-table__table logs-table">
                                <caption class="visually-hidden">{t.logs.archive}</caption>
                                <thead>
                                    <tr>
                                        <th scope="col">{t.logs.column_date}</th>
                                        <th scope="col">{t.logs.stream}</th>
                                        <th scope="col">{t.logs.column_file}</th>
                                        <th scope="col" class="ui-table__table__cell--align-number">
                                            {t.logs.column_size}
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(files ?? []).map((file, fileIndex) => (
                                        <tr key={fileIndex}>
                                            <th scope="row">{display(file?.date)}</th>
                                            <td>{display(file?.stream_label)}</td>
                                            <td class="log-download">
                                                <a class="filename" href={attribute(file?.view_url)}>
                                                    {display(file?.name)}
                                                </a>
                                            </td>
                                            <td class="ui-table__table__cell--align-number">
                                                {display(file?.size_label)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ) : (
                    <p class="context">{t.logs.empty}</p>
                )}
            </section>
        </>
    );
}
