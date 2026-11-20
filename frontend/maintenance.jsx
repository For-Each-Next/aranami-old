/** Render the selected maintenance worklist with native GET controls. */
import { jsx, attribute, display, hasContent } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { ConsistencyFindings, ConsistencyUserscript, MaintenancePagination } from "./checks.jsx";

export function Maintenance(context) {
    const { category_heading, clear_url, selection, t, task_choices, worklist_path } = context;
    return (
        <>
            {ConsistencyUserscript(context)}
            <a href={attribute(worklist_path)} class="back">
                {t.nav.checks}
            </a>
            <div id="maintenance-browser">
                <nav class="maintenance-navigation" aria-label={t.nav.checks}>
                    <details class="navigation-tools maintenance-menu">
                        <summary class="ui-button ui-button--action-default ui-button--weight-normal">
                            {t.nav.checks}
                        </summary>
                        <ul class="navigation-tools-list">
                            {(task_choices ?? []).map((choice, choiceIndex) => (
                                <li key={choiceIndex}>
                                    <a
                                        href={attribute(choice?.url)}
                                        {...(hasContent(choice?.current)
                                            ? { "aria-current": "page" }
                                            : {})}
                                    >
                                        {display(choice?.label)}
                                    </a>
                                </li>
                            ))}
                        </ul>
                    </details>
                </nav>
                <div class="consistency-worklist">
                    <div class="ui-table__header">
                        <div class="ui-table__header__caption">{display(category_heading)}</div>
                        <div class="maintenance-table-actions">
                            <form
                                class="maintenance-search"
                                role="search"
                                action={attribute(worklist_path)}
                                method="get"
                            >
                                {Object.entries(selection ?? {})
                                    .filter(([name, value]) => !["page", "q", "regex"].includes(name))
                                    .map(([name, value], nameIndex) => (
                                        <input
                                            key={nameIndex}
                                            type="hidden"
                                            name={attribute(name)}
                                            value={attribute(value)}
                                        />
                                    ))}
                                <label class="visually-hidden" for="maintenance-query">
                                    {t.backlog.search}
                                </label>
                                <div class="ui-text-input">
                                    <input
                                        class="ui-text-input__input"
                                        id="maintenance-query"
                                        name="q"
                                        type="search"
                                        maxlength="200"
                                        value={attribute(selection?.["q"] ?? "")}
                                        placeholder={attribute(t.backlog.search)}
                                    />
                                </div>
                                <button
                                    type="submit"
                                    class="ui-button ui-button--action-default ui-button--weight-normal"
                                >
                                    {t.backlog.search_action}
                                </button>
                            </form>
                            {hasContent(selection?.["q"] ?? undefined) ||
                            hasContent(selection?.["quality"] ?? undefined) ||
                            hasContent(selection?.["importance"] ?? undefined) ||
                            hasContent(selection?.["quality_to"] ?? undefined) ||
                            hasContent(selection?.["importance_to"] ?? undefined) ||
                            (selection?.["genre"] ?? "all") !== "all" ? (
                                <a href={attribute(clear_url)}>{display(t.backlog["clear"])}</a>
                            ) : null}
                        </div>
                    </div>
                    {ConsistencyFindings(context)}
                    {MaintenancePagination(context)}
                </div>
            </div>
        </>
    );
}
