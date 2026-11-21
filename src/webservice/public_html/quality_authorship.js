/** Sort and paginate saved editor tables without replacing their native cells. */
import { groupedNumber } from "./number_format.js";
import { matchesQualitySelection } from "./quality_matrix.js";

let detailHandlersInstalled = false;
let tableSequence = 0;
const detailRequests = new Map();

/** Keep delayed details consistent with the currently selected matrix cohort. */
export function applyQualityDetailCohort(dialog) {
    const form = document.querySelector("[data-quality-matrix]");
    if (form?.dataset?.directoryUrl && form.qualitySelection) {
        for (const row of dialog.querySelectorAll("[data-matrix-page][data-matrix-importance]")) {
            const {matrixGrade, matrixImportance, matrixYear} = row.dataset;
            row.dataset.cohort = matchesQualitySelection(form.qualitySelection, matrixGrade, matrixImportance, matrixYear) ? "1" : "0";
        }
        return;
    }
    if (form && !form.qualitySelectedIds && form.dataset.selectedPageIds)
        form.qualitySelectedIds = new Set(JSON.parse(form.dataset.selectedPageIds).map(String));
    const ids = form?.qualitySelectedIds;
    if (!ids) return;
    for (const row of dialog.querySelectorAll("[data-matrix-page]"))
        row.dataset.cohort = ids.has(row.dataset.matrixPage) ? "1" : "0";
}

/** Fetch only the requested same-origin dialog and share concurrent attempts. */
export function loadQualityDetail(value, id) {
    const url = new URL(value, location.href);
    if (url.origin !== location.origin) return Promise.reject(new Error("Invalid quality detail URL"));
    url.hash = "";
    const key = `${url.href}#${id}`;
    const existing = document.getElementById(id);
    if (existing?.nodeName === "DIALOG" && existing.dataset.qualityDetailUrl === url.href)
        return Promise.resolve(existing);
    if (detailRequests.has(key)) return detailRequests.get(key);
    const request = (async () => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        try {
            const response = await fetch(url, {
                credentials: "same-origin", redirect: "error", signal: controller.signal,
                headers: {Accept: "text/html"},
            });
            if (response.status === 404) return null;
            if (!response.ok || (response.url && new URL(response.url).origin !== location.origin) ||
                    !response.headers.get("content-type")?.startsWith("text/html"))
                throw new Error("Quality detail unavailable");
            const page = new DOMParser().parseFromString(await response.text(), "text/html");
            const dialog = page.getElementById(id);
            if (dialog?.nodeName !== "DIALOG" ||
                    dialog.querySelector("script, iframe, object, embed, base, link, style"))
                throw new Error("Invalid quality detail");
            dialog.removeAttribute("open");
            dialog.dataset.qualityDetailUrl = url.href;
            return dialog;
        } finally {clearTimeout(timeout);}
    })();
    detailRequests.set(key, request);
    request.then(() => detailRequests.delete(key), () => detailRequests.delete(key));
    return request;
}

/** Resolve an expired detail by finding the same author in the latest report. */
async function refreshQualityDetail(link, expiredUrl) {
    const author = link.closest("[data-matrix-author]")?.dataset.matrixAuthor;
    if (!author || location.pathname !== "/quality-analysis/") return null;
    const reportUrl = new URL(location.href);
    reportUrl.hash = "";
    reportUrl.searchParams.set("render", "html");
    const response = await fetch(reportUrl, {
        credentials: "same-origin", redirect: "error", cache: "no-store",
        signal: AbortSignal.timeout(15000), headers: {Accept: "text/html"},
    });
    if (!response.ok || !response.headers.get("content-type")?.startsWith("text/html")) return null;
    if (!link.isConnected) return null;
    const page = new DOMParser().parseFromString(await response.text(), "text/html");
    const row = [...page.querySelectorAll("[data-matrix-author]")]
        .find(candidate => candidate.dataset.matrixAuthor === author);
    const fresh = row?.querySelector(link.hasAttribute("data-significant-detail")
        ? "a[data-significant-detail]" : "a[data-quality-detail]:not([data-significant-detail])");
    if (!fresh) return null;
    const href = new URL(fresh.getAttribute("href"), reportUrl);
    if (href.href === expiredUrl) return null;
    const id = fresh.dataset.qualityDetail;
    const dialog = await loadQualityDetail(href.href, id);
    if (dialog && link.isConnected) {
        link.href = href.href;
        link.dataset.qualityDetail = id;
        link.setAttribute("aria-controls", id);
    }
    return dialog;
}

/** Enhance native detail links while retaining modified-click navigation. */
export function initializeQualityDetails() {
    if (detailHandlersInstalled) return;
    detailHandlersInstalled = true;
    let intent = 0;
    let pendingIndicator = null;
    const openers = new WeakMap();
    function clearPendingIndicator() {
        if (!pendingIndicator) return;
        pendingIndicator.link.removeAttribute("aria-busy");
        pendingIndicator.status.textContent = "";
        pendingIndicator = null;
    }
    document.addEventListener("keydown", event => {
        if (event.key === "Escape") {intent++; clearPendingIndicator();}
    });
    document.addEventListener("close", event => {
        const opener = openers.get(event.target);
        if (opener?.isConnected) opener.focus();
    }, true);
    document.addEventListener("click", async event => {
        const link = event.target.closest?.("a[data-quality-detail]");
        if (!link || event.defaultPrevented || event.button || event.ctrlKey || event.metaKey ||
                event.shiftKey || event.altKey || link.hasAttribute("download") ||
                (link.target && link.target !== "_self") || typeof fetch !== "function" ||
                typeof DOMParser !== "function" || typeof HTMLDialogElement === "undefined" ||
                typeof HTMLDialogElement.prototype.showModal !== "function") return;
        const url = new URL(link.href, location.href);
        if (url.origin !== location.origin) return;
        event.preventDefault();
        event.stopPropagation();
        clearPendingIndicator();
        const request = ++intent;
        const id = link.dataset.qualityDetail;
        link.setAttribute("aria-busy", "true");
        let status = link.qualityDetailStatus;
        if (!status) {
            status = document.createElement("span");
            status.className = "context";
            status.setAttribute("role", "status");
            link.after(status);
            link.qualityDetailStatus = status;
        }
        const indicator = document.createElement("span");
        indicator.className = "quality-detail-loading";
        indicator.setAttribute("aria-hidden", "true");
        const announcement = document.createElement("span");
        announcement.className = "visually-hidden";
        announcement.textContent = link.dataset.loading || "Loading details…";
        status.replaceChildren(indicator, announcement);
        pendingIndicator = {link, status, request};
        let opened = false;
        try {
            const incoming = await loadQualityDetail(url.href, id) ?? await refreshQualityDetail(link, url.href);
            if (!incoming) throw new Error("Quality detail unavailable");
            if (request !== intent || !link.isConnected) return;
            let dialog = document.getElementById(incoming.id);
            if (dialog !== incoming) {
                dialog?.close();
                dialog?.remove();
                (document.querySelector("[data-quality-results]") || document.body).append(incoming);
                dialog = incoming;
            }
            applyQualityDetailCohort(dialog);
            initializeQualityAuthorship(dialog);
            dialog.dispatchEvent(new Event("quality-detail-open"));
            openers.set(dialog, link);
            link.focus();
            if (!dialog.open) dialog.showModal();
            opened = true;
        } catch {
            if (request === intent && link.isConnected)
                status.textContent = ` ${link.dataset.loadFailed || "Details could not load. Try again or open the link in a new tab."}`;
        } finally {
            if (request === intent) {
                link.removeAttribute("aria-busy");
                if (opened || !link.isConnected) status.textContent = "";
                if (pendingIndicator?.request === request) pendingIndicator = null;
            }
        }
    }, true);
    // Legacy pages retain inline dialogs; enhance each only when it is opened.
    document.addEventListener("click", event => {
        const link = event.target.closest?.('a[aria-haspopup="dialog"]');
        if (!link || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey ||
                link.hasAttribute("data-quality-detail")) return;
        const dialog = document.getElementById(link.getAttribute("aria-controls"));
        if (dialog?.nodeName === "DIALOG") {
            applyQualityDetailCohort(dialog);
            initializeQualityAuthorship(dialog);
            dialog.dispatchEvent(new Event("quality-detail-open"));
        }
    }, true);
}

/** Compare observed values while keeping missing observations last. */
export function compareValues(left, right, descending, locale) {
    if (left === null) return right === null ? 0 : 1;
    if (right === null) return -1;
    const comparison =
        typeof left === "number" && typeof right === "number"
            ? left - right
            : String(left).localeCompare(String(right), locale);
    return descending ? -comparison : comparison;
}

/** Commit a typed page number on Enter or when the field loses focus. */
export function initializeQualityPageInput(pager, goToPage) {
    const input = pager.querySelector(".quality-page-number input");
    if (!input) return;
    const jump = () => {
        const current = Number(input.dataset.currentPage || 1);
        const requested = input.valueAsNumber;
        const page = Number.isFinite(requested)
            ? Math.max(1, Math.min(Number(input.max), Math.trunc(requested))) : current;
        input.value = String(page);
        if (page !== current) {
            input.dataset.currentPage = input.value;
            goToPage(page);
        }
    };
    input.addEventListener("change", jump);
    input.addEventListener("keydown", event => {
        if (event.key === "Enter") {
            event.preventDefault();
            jump();
        }
    });
}

/** Reflect the current page and the valid range after filtering or paging. */
export function updateQualityPageInput(pager, page, pages) {
    const input = pager.querySelector(".quality-page-number input");
    if (!input) return;
    input.max = String(pages);
    input.value = input.dataset.currentPage = String(page);
}

/** Add accessible sorting and pagination to each server-rendered directory. */
export function initializeQualityAuthorship(root = document) {
    initializeQualityDetails();
    for (const host of root.querySelectorAll("[data-quality-authorship-table]")) {
        const dialog = host.closest("dialog");
        if (root === document && dialog && !dialog.open) continue;
        const table = host.querySelector("table");
        if (!table || host.hasAttribute("data-table-enhanced")) continue;
        host.setAttribute("data-table-enhanced", "");
        const tbody = table.querySelector("tbody");
        const headings = [...table.querySelectorAll("thead th")];
        const originalRows = [...tbody.rows];
        const locale = document.documentElement.lang;
        const defaultColumn = Number(
            (host.dataset.defaultSort || "column3").replace("column", ""),
        );
        let column = defaultColumn;
        let descending = true;
        let page = 1;
        let size = 10;
        const buttons = [];
        const pager = document.createElement("nav");
        pager.className = "ui-table-pager";
        pager.setAttribute(
            "aria-label",
            table.querySelector("caption")?.textContent || "",
        );
        const label = document.createElement("label");
        label.className = "ui-table-pager__start";
        label.htmlFor = `quality-page-size-${++tableSequence}`;
        label.textContent = host.dataset.pageSize;
        const select = document.createElement("select");
        select.id = label.htmlFor;
        for (const count of [10, 20, 50]) {
            const option = document.createElement("option");
            option.value = String(count);
            option.textContent =
                host.dataset.rows?.replace("{count}", groupedNumber(count)) ||
                String(count);
            select.append(option);
        }
        label.append(select);
        const status = document.createElement("span");
        status.className = host.dataset.pageNumber
            ? "ui-table-pager__center visually-hidden" : "ui-table-pager__center";
        status.setAttribute("role", "status");
        pager.append(label, status);
        const navigation = document.createElement("div");
        navigation.className = "ui-table-pager__end";
        pager.append(navigation);
        const actions = [];
        for (const [key, destination] of [
            ["first", () => 1],
            ["prev", () => page - 1],
            ["next", () => page + 1],
            ["last", () => Math.max(1, Math.ceil(originalRows.length / size))],
        ]) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "ui-button";
            button.textContent = host.dataset[key];
            button.setAttribute("aria-label", host.dataset[key]);
            button.addEventListener("click", () => {
                page = destination();
                render();
            });
            actions.push(button);
            navigation.append(button);
            if (key === "prev" && host.dataset.pageNumber) {
                const [prefix, suffix] = host.dataset.pageNumber.split("{page}");
                const current = document.createElement("label");
                current.className = "quality-page-number";
                const input = document.createElement("input");
                input.className = "cdx-text-input__input";
                input.type = "number";
                input.inputMode = "numeric";
                input.min = "1";
                input.setAttribute("aria-label", host.dataset.goToPage);
                current.append(prefix, input, suffix);
                navigation.append(current);
            }
        }
        select.addEventListener("change", () => {
            size = Number(select.value);
            page = 1;
            render();
        });
        host.append(pager);
        initializeQualityPageInput(pager, target => { page = target; render(); });

        /** Reorder existing escaped cells and show only the selected page. */
        function render() {
            originalRows.forEach(row => {row.hidden = true;});
            const rows = originalRows.filter(row => row.dataset.cohort !== "0").sort((left, right) => {
                const read = (row) => {
                    const value = row.cells[column].dataset.sort;
                    return value === undefined || value === ""
                        ? null
                        : headings[column].dataset.sortType === "number"
                          ? Number(value)
                          : value;
                };
                return compareValues(
                    read(left),
                    read(right),
                    descending,
                    locale,
                );
            });
            page = Math.min(page, Math.max(1, Math.ceil(rows.length / size)));
            const start = (page - 1) * size;
            for (const [position, row] of rows.entries()) {
                row.hidden = position < start || position >= start + size;
                row.cells[0].textContent = String(position + 1);
                tbody.append(row);
            }
            for (const [position, heading] of headings.entries()) {
                if (position > 0)
                    heading.setAttribute(
                        "aria-sort",
                        position === column
                            ? descending
                                ? "descending"
                                : "ascending"
                            : "none",
                    );
            }
            status.textContent =
                host.dataset.pageStatus
                    ?.replace("{start}", groupedNumber(rows.length ? start + 1 : 0))
                    .replace(
                        "{end}",
                        String(Math.min(start + size, rows.length)),
                    )
                    .replace("{total}", groupedNumber(rows.length)) || "";
            actions[0].disabled = actions[1].disabled = page <= 1;
            actions[2].disabled = actions[3].disabled =
                start + size >= rows.length;
            updateQualityPageInput(pager, page, Math.max(1, Math.ceil(rows.length / size)));
        }
        for (const [position, heading] of headings.entries()) {
            if (!position) continue;
            const button = document.createElement("button");
            button.type = "button";
            button.className = "ui-table__table__sort-button";
            button.textContent = heading.textContent;
            button.title =
                host.dataset.sortCaption?.replace(
                    "{caption}",
                    heading.textContent,
                ) || heading.textContent;
            button.addEventListener("click", () => {
                descending = column === position ? !descending : false;
                column = position;
                page = 1;
                render();
            });
            buttons.push(button);
            heading.replaceChildren(button);
        }
        const cohortChanged = () => {
            if (!host.isConnected) {
                document.removeEventListener("quality-cohort-change", cohortChanged);
                return;
            }
            page = 1;
            render();
        };
        document.addEventListener("quality-cohort-change", cohortChanged);
        if (dialog) {
            dialog.addEventListener("quality-detail-open", () => {
                column = defaultColumn;
                descending = true;
                page = 1;
                render();
            });
        }
        render();
    }
}
