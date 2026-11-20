/** Render saved consistency findings, evidence and pagination. */
import { jsx, iconHref, assetUrl, attribute, display, hasContent } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { SourceUpdated } from "./shared.jsx";

export function ConsistencyFindings(context) {
    const { consistency_findings, consistency_ordered, consistency_status, start, t } = context;
    return (
        <section class="section-flat consistency-section" aria-labelledby="maintenance-consistency">
            <h2 id="maintenance-consistency">{t.consistency.heading}</h2>
            {hasContent(consistency_findings) ? (
                ((FindingsTag) => (
                    <FindingsTag
                        class={
                            "consistency-findings consistency-cards" +
                            (hasContent(consistency_ordered) ? " consistency-history-cards" : "")
                        }
                    >
                        {(consistency_findings ?? []).map((finding, findingIndex) => (
                            <Fragment key={findingIndex}>
                                {hasContent(consistency_ordered) ? (
                                    ConsistencyFinding({
                                        ...context,
                                        finding: finding,
                                        finding_ordinal: start + findingIndex,
                                    })
                                ) : (
                                    <li>
                                        {ConsistencyFinding({
                                            ...context,
                                            finding: finding,
                                        })}
                                    </li>
                                )}
                            </Fragment>
                        ))}
                    </FindingsTag>
                ))(hasContent(consistency_ordered) ? "div" : "ul")
            ) : hasContent(consistency_status?.empty) ? (
                <p>{t.consistency.empty}</p>
            ) : (
                <p>{t.backlog.empty}</p>
            )}
            {!hasContent(consistency_status?.observed_at) ||
            hasContent(consistency_status?.incomplete) ? (
                <p>{display(consistency_status?.message)}</p>
            ) : null}
            {SourceUpdated({
                ...context,
                updated: consistency_status?.updated,
            })}
        </section>
    );
}

export function ConsistencyCard(context) {
    const { finding, finding_ordinal, language_tag, t } = context;
    return (
        <article class="ui-card consistency-card" aria-labelledby={attribute(finding?.heading_id)}>
            <div class="ui-card__text">
                <div class="ui-card__text__title">
                    <h3 id={attribute(finding?.heading_id)}>
                        {finding_ordinal !== undefined ? (
                            <>
                                <span class="consistency-ordinal">
                                    {display(finding_ordinal)}
                                    {"."}
                                </span>{" "}
                            </>
                        ) : null}
                        <bdi lang="zh">{display(finding?.article)}</bdi>
                        <span class="consistency-talk">
                            {display(language_tag === "en" ? " (" : "（")}
                            {display(finding?.talk)}
                            {display(language_tag === "en" ? ")" : "）")}
                        </span>
                    </h3>
                </div>
                <div class="ui-card__text__description">
                    {hasContent(finding?.missing_fields) ? (
                        <p class="consistency-missing">
                            {t.consistency.missing}
                            {(finding?.missing_fields ?? []).map((field, fieldIndex, fieldItems) => (
                                <Fragment key={fieldIndex}>
                                    <code>{display(field)}</code>
                                    {!hasContent(fieldIndex === fieldItems.length - 1)
                                        ? display(language_tag === "en" ? ", " : "、")
                                        : null}
                                </Fragment>
                            ))}
                        </p>
                    ) : (
                        <p class="consistency-description">{display(finding?.description)}</p>
                    )}
                    {hasContent(finding?.suggestion_note) ? (
                        <p class="consistency-description">{display(finding?.suggestion_note)}</p>
                    ) : null}
                    {hasContent(finding?.code) ? (
                        <div class="consistency-code">
                            <div class="ui-text-area ui-text-area--status-default">
                                <textarea
                                    id={attribute(finding?.code_id)}
                                    class="ui-text-area__textarea ui-text-area__textarea--has-value"
                                    aria-label={attribute(t.consistency.parameter_code)}
                                    lang="en"
                                    dir="ltr"
                                    rows="2"
                                    spellcheck="false"
                                    readonly
                                >
                                    {display(finding?.code)}
                                </textarea>
                            </div>
                            <div class="newsletter-copy-controls consistency-copy-controls">
                                <button
                                    type="button"
                                    class="ui-button ui-button--action-default ui-button--weight-normal"
                                    data-copy-target={attribute(finding?.code_id)}
                                    data-copy-success={attribute(t.consistency.code_copied)}
                                    data-copy-failure={attribute(t.newsletter.copy_failure)}
                                >
                                    {t.consistency.copy_code}
                                </button>
                                {(finding?.repair_actions ?? []).map((action, actionIndex) => (
                                    <a
                                        key={actionIndex}
                                        href={attribute(action?.url)}
                                        target="_blank"
                                        rel="noopener"
                                        class="ui-button ui-button--fake-button ui-button--fake-button--enabled consistency-review-action"
                                    >
                                        {display(action?.label)}
                                    </a>
                                ))}
                                <span data-copy-status={""} role="status" aria-live="polite"></span>
                            </div>
                        </div>
                    ) : null}
                    {hasContent(finding?.repair_actions) && !hasContent(finding?.code) ? (
                        <p class="consistency-review-actions">
                            {(finding?.repair_actions ?? []).map((action, actionIndex) => (
                                <a
                                    key={actionIndex}
                                    href={attribute(action?.url)}
                                    target="_blank"
                                    rel="noopener"
                                    class="ui-button ui-button--fake-button ui-button--fake-button--enabled consistency-review-action"
                                >
                                    {display(action?.label)}
                                </a>
                            ))}
                        </p>
                    ) : null}
                    {hasContent(finding?.obsolete_parameters) && hasContent(finding?.code) ? (
                        <p class="consistency-migration">
                            {t.consistency.remove_parameters}
                            {(finding?.obsolete_parameters ?? []).map((name, nameIndex, nameItems) => (
                                <Fragment key={nameIndex}>
                                    <code>{display(name)}</code>
                                    {!hasContent(nameIndex === nameItems.length - 1)
                                        ? display(language_tag === "en" ? ", " : "、")
                                        : null}
                                </Fragment>
                            ))}
                        </p>
                    ) : null}
                    {hasContent(finding?.legacy_dyk_count) && hasContent(finding?.code) ? (
                        <p class="consistency-migration">
                            {display(
                                t.consistency.remove_dyk.replaceAll(
                                    "{count}",
                                    String(finding?.legacy_dyk_count),
                                ),
                            )}
                        </p>
                    ) : null}
                    {hasContent(finding?.suggestions) ? (
                        <>
                            <dl class="consistency-metrics">
                                {(finding?.suggestions ?? []).map((metric, metricIndex) => (
                                    <div key={metricIndex}>
                                        <dt>{display(metric?.label)}</dt>
                                        <dd
                                            {...(hasContent(metric?.unknown)
                                                ? {
                                                      class: "consistency-unknown",
                                                  }
                                                : {})}
                                        >
                                            {display(metric?.value)}
                                        </dd>
                                    </div>
                                ))}
                            </dl>
                            <p class="consistency-snapshot">
                                {t.consistency.snapshot_note}
                                {hasContent(finding?.snapshot_date) ? (
                                    <>
                                        {" "}
                                        <time datetime={attribute(finding?.snapshot_date)}>
                                            {display(finding?.snapshot_date)}
                                        </time>
                                        {"."}
                                    </>
                                ) : null}
                            </p>
                            <p class="consistency-snapshot">{t.consistency.quality_note}</p>
                        </>
                    ) : null}
                </div>
                <div class="ui-card__text__supporting-text">
                    {hasContent(finding?.latest_date) ? (
                        <div class="consistency-card-links">
                            <time datetime={attribute(finding?.latest_date)}>
                                {display(finding?.latest_date)}
                            </time>
                        </div>
                    ) : null}
                    {ConsistencyEvidence(context)}
                </div>
            </div>
        </article>
    );
}

export function ConsistencyEvidence(context) {
    const { finding, t } = context;
    return (
        <details class="ui-accordion consistency-evidence">
            <summary>
                <h4 class="ui-accordion__header">
                    {display(
                        t.consistency.evidence_details.replaceAll(
                            "{count}",
                            String(finding?.evidence?.length ?? 0),
                        ),
                    )}
                </h4>
            </summary>
            <div class="ui-accordion__content">
                <dl class="consistency-evidence-list">
                    {(finding?.evidence ?? []).map((evidence, evidenceIndex) => (
                        <div key={evidenceIndex}>
                            <dt>
                                {hasContent(evidence?.expected_field) ? (
                                    <code>{display(evidence?.expected_field)}</code>
                                ) : (
                                    display(evidence?.event_label)
                                )}
                                {hasContent(evidence?.event_date) ? (
                                    <>
                                        {" "}
                                        <time datetime={attribute(evidence?.event_date)}>
                                            {display(evidence?.event_date)}
                                        </time>
                                    </>
                                ) : null}
                            </dt>
                            <dd>
                                {display(evidence?.source)}
                                {" · "}
                                {display(evidence?.checked)}
                            </dd>
                        </div>
                    ))}
                </dl>
            </div>
        </details>
    );
}

export function ConsistencyFinding(context) {
    return ConsistencyCard(context);
}

export function ConsistencyUserscript(context) {
    const { t } = context;
    return (
        <p class="consistency-userscript" id="consistency-userscript">
            {t.consistency.userscript_note}{" "}
            <a href={assetUrl(context, "consistency-repair.user.js")}>
                {t.consistency.userscript_install}
            </a>
        </p>
    );
}

export function MaintenancePagination(context) {
    const { first, following, last, previous, range_label, selection, t, worklist_path } = context;
    return (
        <nav class="ui-table-pager ui-table__pagination--bottom" aria-label={t.nav.checks}>
            <form class="page-size ui-table-pager__start" action={attribute(worklist_path)} method="get">
                {Object.entries(selection ?? {})
                    .filter(([name, value]) => !["page", "limit"].includes(name))
                    .map(([name, value], nameIndex) => (
                        <input
                            key={nameIndex}
                            type="hidden"
                            name={attribute(name)}
                            value={attribute(value)}
                        />
                    ))}
                <label class="visually-hidden" for="maintenance-limit">
                    {t.backlog.rows}
                </label>
                <select class="ui-select" id="maintenance-limit" name="limit">
                    {["10", "20", "50"].map((size, sizeIndex) => (
                        <option
                            key={sizeIndex}
                            value={attribute(size)}
                            {...(size === (selection?.["limit"] ?? "10") ? { selected: true } : {})}
                        >
                            {display(size)}
                        </option>
                    ))}
                </select>
                <noscript>
                    <button
                        class="ui-button ui-button--action-default ui-button--weight-normal page-size-submit"
                        type="submit"
                    >
                        {t.backlog.go}
                    </button>
                </noscript>
            </form>
            <div class="ui-table-pager__center">
                <div class="ui-table__pagination-status--long">{display(range_label)}</div>
                <div class="ui-table__pagination-status--short">{display(range_label)}</div>
            </div>
            <div class="ui-table-pager__end">
                {[
                    ["first", first, t.backlog.first, "first"],
                    ["previous", previous, t.backlog.previous, "prev"],
                    ["next", following, t.backlog.next, "next"],
                    ["last", last, t.backlog.last, "last"],
                ].map(([name, url, label, relation], nameIndex) => (
                    <Fragment key={nameIndex}>
                        {hasContent(url) ? (
                            <a
                                class="ui-button ui-button--fake-button ui-button--fake-button--enabled ui-button--icon-only ui-button--action-default ui-button--weight-quiet"
                                href={attribute(url)}
                                rel={attribute(relation)}
                                data-page={attribute(name)}
                                aria-label={attribute(label)}
                                title={attribute(label)}
                            >
                                <span class="ui-icon ui-icon--medium">
                                    <svg viewBox="0 0 20 20" aria-hidden="true">
                                        <use href={iconHref(context, "page-") + attribute(name)}></use>
                                    </svg>
                                </span>
                            </a>
                        ) : (
                            <button
                                class="ui-button ui-button--icon-only ui-button--action-default ui-button--weight-quiet"
                                type="button"
                                data-page={attribute(name)}
                                aria-label={attribute(label)}
                                title={attribute(label)}
                                disabled
                            >
                                <span class="ui-icon ui-icon--medium">
                                    <svg viewBox="0 0 20 20" aria-hidden="true">
                                        <use href={iconHref(context, "page-") + attribute(name)}></use>
                                    </svg>
                                </span>
                            </button>
                        )}
                    </Fragment>
                ))}
            </div>
        </nav>
    );
}
