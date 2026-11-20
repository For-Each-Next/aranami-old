/** Provide the standard footer for tables without their own paging controls. */
const managed = [
    "[data-quality-analysis]",
    "[data-quality-authorship-table]",
    "[data-execution-history]",
    ".dataset-preview-table",
    "#analysis-coverage-dialog",
    "#analysis-chart-articles",
    ".consistency-worklist",
].join(", ");
const pagers = new WeakMap();

/** Create one footer and keep its controls available for empty results. */
function attachPager(table, labels) {
    if (table.closest(managed)) return;
    const existing = pagers.get(table);
    if (existing) { existing(); return; }
    const nav = document.createElement("nav");
    nav.className = "ui-table-pager";
    const caption = table.caption?.textContent.trim() || table.parentElement.getAttribute("aria-label");
    nav.setAttribute("aria-label", caption || labels.size);
    const size = document.createElement("select");
    for (const count of [20, 50, 100]) {
        const option = document.createElement("option");
        option.value = String(count);
        option.textContent = String(count);
        size.append(option);
    }
    const label = document.createElement("label");
    label.className = "ui-table-pager__start";
    label.append(labels.size + " ", size);
    const status = document.createElement("span");
    status.className = "ui-table-pager__center";
    status.setAttribute("aria-live", "polite");
    const actions = document.createElement("div");
    actions.className = "ui-table-pager__end";
    let page = 1;
    let last = 1;
    const buttons = [labels.first, labels.previous, labels.next, labels.last].map((text, index) => {
        const button = document.createElement("button");
        button.className = "ui-button";
        button.type = "button";
        button.textContent = text;
        button.addEventListener("click", () => {
            page = [1, page - 1, page + 1, last][index];
            render();
        });
        actions.append(button);
        return button;
    });
    function render() {
        if (!nav.isConnected) {
            const wrapper = table.closest(".table-scroll, .ui-table__table-wrapper") || table;
            wrapper.after(nav);
        }
        const rows = [...table.tBodies].flatMap(body => [...body.rows]);
        const limit = Number(size.value);
        last = Math.max(1, Math.ceil(rows.length / limit));
        page = Math.max(1, Math.min(page, last));
        const start = (page - 1) * limit;
        rows.forEach((row, index) => {
            const hidden = index < start || index >= start + limit;
            if (row.hidden !== hidden) row.hidden = hidden;
        });
        const label = labels.status
            .replace("{start}", rows.length ? start + 1 : 0)
            .replace("{end}", Math.min(start + limit, rows.length))
            .replace("{total}", rows.length);
        if (status.textContent !== label) status.textContent = label;
        buttons[0].disabled = buttons[1].disabled = page === 1;
        buttons[2].disabled = buttons[3].disabled = page === last;
    }
    size.addEventListener("change", () => { page = 1; render(); });
    nav.append(label, status, actions);
    pagers.set(table, render);
    render();
}

/** Enhance native and subsequently opened dialog tables in one place. */
export function initializeTablePagers() {
    const authored = document.body?.dataset.tablePageLabels;
    if (!authored || document.body.dataset.tablePagersReady || typeof MutationObserver !== "function") return;
    document.body.dataset.tablePagersReady = "true";
    const [size, status, first, previous, next, last] = JSON.parse(authored);
    const labels = {size, status, first, previous, next, last};
    function enhance(root) {
        if (root.matches?.("table")) attachPager(root, labels);
        for (const table of root.querySelectorAll?.("table") || []) attachPager(table, labels);
    }
    enhance(document.body);
    const observer = new MutationObserver(records => {
        const dirty = new Set();
        for (const record of records) {
            const table = record.target.closest?.("table");
            if (table) dirty.add(table);
            for (const node of record.addedNodes) if (node.nodeType === 1) enhance(node);
            for (const node of record.removedNodes) {
                if (node.nodeType === 1 && node.classList.contains("ui-table-pager")) {
                    const table = record.target.querySelector("table");
                    if (table) dirty.add(table);
                }
            }
        }
        for (const table of dirty) if (table.isConnected) attachPager(table, labels);
    });
    observer.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"]});
}
