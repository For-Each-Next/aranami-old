/** Present the grouped consistency checks and their saved coverage. */
import { jsx, attribute, defaultContents, display, hasContent } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { SourceUpdated } from "./shared.jsx";
import { ConsistencyFinding, ConsistencyUserscript } from "./checks.jsx";

export function ConsistencyContents(context) {
    const { consistency_sections } = context;
    return hasContent(consistency_sections) ? (
        <ul>
            {(consistency_sections ?? []).map((section, sectionIndex) => (
                <li key={sectionIndex}>
                    <a href={"#" + attribute(section?.key)}>{display(section?.label)}</a>
                </li>
            ))}
        </ul>
    ) : (
        display(defaultContents(context))
    );
}

export function Consistency(context) {
    const { consistency_sections, consistency_status, t } = context;
    return (
        <>
            {ConsistencyUserscript(context)}
            <div id="maintenance-consistency" class="consistency-section">
                <div class="consistency-groups">
                    {(consistency_sections ?? []).map((section, sectionIndex) => (
                        <Fragment key={sectionIndex}>
                            {((FindingsTag) => (
                                <section
                                    class="consistency-group"
                                    aria-labelledby={attribute(section?.key)}
                                >
                                    <header class="consistency-group-heading">
                                        <h2 id={attribute(section?.key)}>{display(section?.label)}</h2>
                                        <span class="consistency-count">
                                            {display(
                                                !(section?.total_count == null)
                                                    ? section?.total_count
                                                    : (section?.findings?.length ?? 0),
                                            )}
                                        </span>
                                    </header>
                                    <FindingsTag
                                        class={
                                            "consistency-findings consistency-cards" +
                                            (hasContent(section?.ordered)
                                                ? " consistency-history-cards"
                                                : "")
                                        }
                                    >
                                        {(section?.findings ?? []).map((finding, findingIndex) => (
                                            <Fragment key={findingIndex}>
                                                {hasContent(section?.ordered) ? (
                                                    ConsistencyFinding({
                                                        ...context,
                                                        section: section,
                                                        finding: finding,
                                                        finding_ordinal:
                                                            section?.offset + findingIndex + 1,
                                                    })
                                                ) : (
                                                    <li>
                                                        {ConsistencyFinding({
                                                            ...context,
                                                            section: section,
                                                            finding: finding,
                                                        })}
                                                    </li>
                                                )}
                                            </Fragment>
                                        ))}
                                    </FindingsTag>
                                    {hasContent(section?.pagination) ? (
                                        <nav
                                            class="ui-table-pager history-pagination consistency-pagination"
                                            aria-label={attribute(section?.label)}
                                        >
                                            {[
                                                ["previous", "prev", t.backlog.previous],
                                                ["next", "next", t.backlog.next],
                                            ].map(([name, relation, label], nameIndex) => (
                                                <Fragment key={nameIndex}>
                                                    {name === "next" ? (
                                                        <span>
                                                            {display(section?.pagination?.label)}
                                                        </span>
                                                    ) : null}
                                                    {hasContent(section?.pagination?.[name]) ? (
                                                        <a
                                                            class="ui-button ui-button--fake-button ui-button--fake-button--enabled"
                                                            href={attribute(section?.pagination?.[name])}
                                                            rel={attribute(relation)}
                                                        >
                                                            {display(label)}
                                                        </a>
                                                    ) : (
                                                        <button class="ui-button" type="button" disabled>
                                                            {display(label)}
                                                        </button>
                                                    )}
                                                </Fragment>
                                            ))}
                                        </nav>
                                    ) : null}
                                </section>
                            ))(hasContent(section?.ordered) ? "div" : "ul")}
                        </Fragment>
                    ))}
                </div>
                {hasContent(consistency_status?.empty) ? <p>{t.consistency.empty}</p> : null}
                {!hasContent(consistency_status?.observed_at) ||
                hasContent(consistency_status?.incomplete) ? (
                    <p>{display(consistency_status?.message)}</p>
                ) : null}
                {SourceUpdated({
                    ...context,
                    updated: consistency_status?.updated,
                })}
            </div>
        </>
    );
}
