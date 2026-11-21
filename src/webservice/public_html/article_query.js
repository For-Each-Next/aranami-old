/** Edit and pre-check a saved-data Article List query. */

const predicates = ["cat", "tl", "link", "backlink", "wp", "class", "imp", "has_wiki"];
const pagePredicates = new Set(predicates.slice(0, 4));
const operators = ["and", "or", "not"];
const example = 'class("B", site="en") & class({"小作品", "小列表"})';

function element(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
}

function button(label, action, primary = false) {
    const item = element("button", label, primary
        ? "cdx-button cdx-button--action-progressive cdx-button--weight-primary"
        : "cdx-button");
    item.type = "button";
    item.addEventListener("click", action);
    return item;
}

function select(label, items, current, change) {
    const item = element("select", undefined, "article-query-select");
    item.setAttribute("aria-label", label);
    for (const [key, name] of items) {
        const option = element("option", name);
        option.value = key;
        item.append(option);
    }
    item.value = current;
    item.addEventListener("change", () => change(item.value));
    return item;
}

function field(label, control) {
    const wrapper = element("label", undefined, "article-query-field");
    wrapper.append(element("span", label), control);
    return wrapper;
}

function input(value, change, type = "text") {
    const item = element("input", undefined, "cdx-text-input__input");
    item.type = type;
    item.value = value ?? "";
    if (type === "number") {
        item.min = "0";
        item.max = "5";
        item.step = "1";
    } else item.maxLength = 255;
    item.addEventListener("input", () => change(item.value));
    return item;
}

function checkbox(label) {
    const item = element("input");
    item.type = "checkbox";
    item.checked = true;
    const wrapper = element("label", undefined, "article-query-toggle");
    wrapper.append(item, document.createTextNode(label));
    return {item, wrapper};
}

function argument(value) {
    return Array.isArray(value) ? "{" + value.map(item => JSON.stringify(item)).join(", ") + "}"
        : JSON.stringify(value);
}

/** Serialize edited blocks using the server's validated expression shape. */
export function serializeArticleQuery(node) {
    if (!node) return "";
    if (node.op === "term") {
        const named = Object.entries(node.options).map(([key, value]) => key + "=" + argument(value));
        return node.name + "(" + [argument(node.value), ...named].join(", ") + ")";
    }
    const children = node.children.map(serializeArticleQuery);
    if (node.op === "not") return "~" + children[0];
    return "(" + children.join(node.op === "and" ? " & " : " | ") + ")";
}

function condition() {
    return {op: "term", name: "cat", value: "", options: {}};
}

function leaves(node) {
    if (!node) return [];
    return node.op === "term" ? [node] : node.children.flatMap(leaves);
}

function statusText(result, labels) {
    const value = result.resolved ? result.entered + " → " + result.resolved : result.entered;
    return labels[result.site] + " · " + value + " · " + labels[result.status];
}

/** Connect the two editors to the confirmed directory selection. */
export function initializeArticleQuery(host, changed) {
    const panel = host.querySelector("[data-article-query]");
    if (!panel) return null;
    const labels = JSON.parse(panel.dataset.articleQuery);
    const workspace = element("div", undefined, "article-query-workspace");
    const modes = element("div", undefined, "article-query-actions");
    const blocks = element("div", undefined, "article-query-blocks");
    const code = element("textarea", undefined, "cdx-text-area__textarea article-query-code");
    code.rows = 4;
    code.maxLength = 2048;
    code.spellcheck = false;
    code.setAttribute("aria-label", labels.code);
    const highlighted = element("pre", undefined, "article-query-source");
    highlighted.setAttribute("aria-label", labels.precheck);
    const feedback = element("p", undefined, "context article-query-feedback");
    feedback.setAttribute("role", "status");
    const observed = element("p", undefined, "context article-query-observed");
    observed.setAttribute("role", "status");
    const checks = element("ul", undefined, "article-query-checks");
    checks.setAttribute("aria-label", labels.precheck);
    checks.setAttribute("aria-live", "polite");
    const actions = element("div", undefined, "article-query-actions");
    const fix = checkbox(labels.fix);
    const redirects = checkbox(labels.redirects);
    let tree = null;
    let mode = "blocks";
    let results = [];
    let applied = null;
    let pending, timer;

    const blockMode = button(labels.blocks, () => switchMode("blocks"));
    const codeMode = button(labels.code, () => switchMode("code"));
    modes.append(blockMode, codeMode, button(labels.example, () => {
        code.value = example;
        switchMode("code");
        discardChecks();
        void inspect(false);
        code.focus();
    }));
    const preview = button(labels.precheck, () => void inspect(true));
    const run = button(labels.run, () => void apply(), true);
    actions.append(fix.wrapper, redirects.wrapper, preview, run,
        button(labels.clear, () => clear()));
    workspace.append(modes, blocks, code, actions, feedback, highlighted, checks, observed);
    panel.append(workspace);
    panel.hidden = false;

    function switchMode(value) {
        mode = value;
        code.hidden = mode !== "code";
        blocks.hidden = mode !== "blocks";
        blockMode.setAttribute("aria-pressed", String(mode === "blocks"));
        codeMode.setAttribute("aria-pressed", String(mode === "code"));
        highlighted.hidden = mode !== "code" || !highlighted.childNodes.length;
    }

    function discardChecks() {
        clearTimeout(timer);
        pending?.abort();
        results = [];
        feedback.textContent = "";
        checks.replaceChildren();
        highlighted.replaceChildren();
        highlighted.hidden = true;
        code.removeAttribute("aria-invalid");
        for (const item of blocks.querySelectorAll("[data-query-missing]")) {
            item.removeAttribute("data-query-missing");
        }
    }

    function edited(render = false) {
        code.value = serializeArticleQuery(tree);
        discardChecks();
        if (render) renderBlocks();
    }

    function groupSelector(node, replace) {
        return select(labels.wrap, [["", labels.wrap], ...operators.map(key => [key, labels[key]])],
            "", op => {
                if (op) replace({op, children: op === "not" ? [node] : [node, condition()]});
            });
    }

    function stringField(label, value, change) {
        return field(label, input(value, text => { change(text); edited(); }));
    }

    function valueFields(term, name, label, item, set, showMissing = false) {
        const container = element("div", undefined, "article-query-values");
        const values = Array.isArray(item) ? item : [item ?? ""];
        values.forEach((current, index) => {
            const control = input(current, value => {
                values[index] = value;
                set(values.length > 1 ? values : value);
                edited();
            });
            if (showMissing && results.some(result => result.start === term.start
                && result.entered === current && result.status === "missing")) {
                control.dataset.queryMissing = "";
                control.title = labels.missing;
            }
            const row = element("div", undefined, "article-query-value-row");
            row.append(field(label, control));
            if (values.length > 1) row.append(button(labels.remove, () => {
                values.splice(index, 1);
                set(values.length > 1 ? values : values[0]);
                edited(true);
            }));
            container.append(row);
        });
        container.append(button(labels.add_value, () => {
            set([...values, ""]);
            edited(true);
        }));
        container.dataset.queryValues = name;
        return container;
    }

    function termBlock(term) {
        const form = element("div", undefined, "article-query-term");
        const {name, options} = term;
        const choose = select(labels.predicate, predicates.map(key => [key, labels[key]]), name, next => {
            term.name = next;
            term.value = next === "has_wiki" ? "en" : name === "has_wiki" ? "" : term.value;
            term.options = next !== "has_wiki" && options.site ? {site: options.site} : {};
            edited(true);
        });
        form.append(field(labels.predicate, choose));
        const sites = ["zh", "en"].map(site => [site, labels[site]]);
        if (name === "has_wiki") {
            form.append(field(labels.site, select(labels.site, sites, term.value, value => {
                term.value = value;
                edited();
            })));
            return form;
        }
        form.append(field(labels.site, select(labels.site, sites, options.site ?? "zh", site => {
            if (site === "zh") delete options.site;
            else options.site = site;
            edited();
        })));
        if (pagePredicates.has(name)) {
            form.append(field(labels.on,
                select(labels.on, ["main", "talk"].map(page => [page, labels[page]]), options.on ?? "main", on => {
                    if (on === "main") delete options.on;
                    else options.on = on;
                    edited();
                })));
        }
        if (name === "cat") {
            form.append(field(labels.depth, input(options.depth ?? 0, depth => {
                options.depth = Number(depth);
                edited();
            }, "number")));
        }
        form.append(valueFields(term, "value", labels.value, term.value, value => { term.value = value; }, true));
        if (name === "class" || name === "imp") {
            const project = stringField(labels.wp, options.project, value => {
                if (value.trim()) options.project = value;
                else delete options.project;
            });
            if (results.some(result => result.start === term.start && result.status === "missing")) {
                project.dataset.queryMissing = "";
                project.title = labels.missing;
            }
            form.append(project);
        }
        if (name === "wp") {
            for (const [key, label] of [["class", labels.class], ["importance", labels.imp]]) {
                form.append(valueFields(term, key, label, options[key], value => {
                    if (value === "") delete options[key];
                    else options[key] = value;
                }));
            }
        }
        return form;
    }

    function block(node, replace) {
        const item = element("div", undefined, "article-query-block");
        item.dataset.queryOp = node.op;
        const toolbar = element("div", undefined, "article-query-actions");
        if (node.op !== "term") {
            toolbar.append(select(labels.edit_group, operators.map(key => [key, labels[key]]), node.op, op => {
                if (op === "not" && node.children.length > 1) {
                    replace({op, children: [node]});
                } else {
                    node.op = op;
                    if (op !== "not" && node.children.length === 1) node.children.push(condition());
                    edited(true);
                }
            }));
        }
        toolbar.append(groupSelector(node, replace), button(labels.remove, () => replace(null)));
        item.append(toolbar);
        if (node.op === "term") item.append(termBlock(node));
        else {
            for (const [index, child] of node.children.entries()) {
                item.append(block(child, value => {
                    if (value) node.children[index] = value;
                    else node.children.splice(index, 1);
                    if (node.children.length) edited(true);
                    else replace(null);
                }));
            }
            if (node.op !== "not") item.append(button(labels.add, () => {
                node.children.push(condition());
                edited(true);
            }));
        }
        return item;
    }

    function renderBlocks() {
        const interactive = "input, select, button";
        const focus = [...blocks.querySelectorAll(interactive)].indexOf(document.activeElement);
        const startsCondition = focus === 0 && blocks.firstElementChild?.tagName === "BUTTON";
        if (tree) {
            blocks.replaceChildren(block(tree, next => { tree = next; edited(true); }));
        } else {
            blocks.replaceChildren(button(labels.add, () => { tree = condition(); edited(true); }));
        }
        if (focus >= 0) {
            const controls = blocks.querySelectorAll(interactive);
            const next = (startsCondition && blocks.querySelector('input[type="text"]'))
                || controls[Math.min(focus, controls.length - 1)];
            next?.focus();
        }
    }

    function showChecks() {
        checks.replaceChildren(...results.map(result => {
            const item = element("li", statusText(result, labels));
            item.dataset.queryStatus = result.status;
            if (!result.resolved) {
                for (const candidate of result.suggestions ?? []) {
                    item.append(" ", button(candidate, () => {
                        const term = leaves(tree).find(leaf => leaf.start === result.start);
                        if (!term) return;
                        term.value = Array.isArray(term.value)
                            ? term.value.map(value => value === result.entered ? candidate : value)
                            : candidate;
                        edited(true);
                        void inspect(true);
                    }));
                }
            }
            return item;
        }));
        highlighted.replaceChildren();
        const source = [...code.value];
        let position = 0;
        for (const term of leaves(tree)) {
            if (!results.some(result => result.start === term.start && result.status === "missing")) continue;
            highlighted.append(source.slice(position, term.start).join(""));
            const warning = element("span", source.slice(term.start, term.end).join(""));
            warning.dataset.queryStatus = "missing";
            highlighted.append(warning);
            position = term.end;
        }
        if (position) highlighted.append(source.slice(position).join(""));
        highlighted.hidden = mode !== "code" || !position;
    }

    /** Use the server parser for code edits and resolve titles on explicit checks. */
    async function inspect(precheck) {
        clearTimeout(timer);
        pending?.abort();
        const request = new AbortController();
        pending = request;
        const expression = code.value;
        const params = {
            expression,
            preview: precheck ? "1" : "0",
            redirects: redirects.item.checked ? "1" : "0",
            variants: fix.item.checked ? "1" : "0",
        };
        if (precheck) feedback.textContent = labels.loading;
        try {
            const query = "/article-list/query/?" + new URLSearchParams(params);
            const response = await fetch(query, {
                credentials: "same-origin", redirect: "error",
                signal: AbortSignal.any([request.signal, AbortSignal.timeout(15000)]),
                headers: {Accept: "application/json"},
            });
            const result = await response.json();
            if (request.signal.aborted || !panel.isConnected) return null;
            if (response.status === 422 && result.query_error) {
                code.setAttribute("aria-invalid", "true");
                feedback.textContent = labels.syntax.replace("{position}", String(result.offset + 1));
                if (document.documentElement.lang === "en") feedback.textContent += " " + result.query_error;
                return null;
            }
            if (!response.ok) throw new Error("Article query unavailable");
            code.removeAttribute("aria-invalid");
            feedback.textContent = "";
            tree = result.tree;
            results = result.checks ?? [];
            renderBlocks();
            showChecks();
            return {result, expression, params};
        } catch {
            if (!request.signal.aborted && panel.isConnected) feedback.textContent = labels.failed;
            return null;
        }
    }

    async function apply() {
        const checked = await inspect(true);
        if (!checked) return;
        const {result, expression, params} = checked;
        applied = expression.trim() ? {
            expression,
            query_redirects: params.redirects === "1",
            query_variants: params.variants === "1",
            ...(result.generation ? {query_generation: result.generation} : {}),
        } : null;
        if (!applied) observed.textContent = "";
        changed();
    }

    function clear(notify = true) {
        tree = null;
        applied = null;
        code.value = "";
        observed.textContent = "";
        edited(true);
        if (notify) changed();
    }

    code.addEventListener("input", () => {
        discardChecks();
        timer = setTimeout(() => void inspect(false), 240);
    });
    for (const toggle of [fix.item, redirects.item]) toggle.addEventListener("change", discardChecks);
    switchMode("blocks");
    renderBlocks();
    return {
        clear,
        options: () => applied ?? {},
        updated(result) {
            if (!applied || !result) return;
            if (result.generation) applied.query_generation = result.generation;
            if (!result.observed_at) {
                observed.textContent = labels.unavailable;
                return;
            }
            const locale = document.documentElement.lang;
            const time = new Intl.DateTimeFormat(locale, {
                dateStyle: "medium", timeStyle: "short", timeZone: "UTC",
            }).format(new Date(result.observed_at)) + " UTC";
            observed.textContent = labels.observed.replace("{time}", time) + (result.unknown
                ? " " + labels.unknown.replace("{count}", new Intl.NumberFormat(locale).format(result.unknown))
                : "");
        },
        failed() { if (applied) feedback.textContent = labels.failed; },
    };
}
