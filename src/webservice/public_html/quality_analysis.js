/** Filter and sort the complete saved article list without source requests. */
import { groupedNumber } from "./number_format.js";
import { compareValues, initializeQualityAuthorship, initializeQualityPageInput, updateQualityPageInput } from "./quality_authorship.js";
import { initializeQualityCoverage } from "./quality_coverage.js";
import { initializeQualityChartControls } from "./quality_chart_controls.js";
import { traditional } from "./quality_search_characters.js";
import { initializeQualityFigures, initializeQualityMatrix, initializeQualitySelection, prepareCatalogRows, catalogRows, articleElement, qualityMetadata, loadQualityMetadata, directoryRows, requestQualityPage } from "./quality_matrix.js";

/** Keep the prepared overview usable while its controls load after paint. */
export function initializeQualityPage(previous = {}) {
    const form = document.querySelector("[data-quality-matrix]");
    initializeQualityFigures(form);
    if (typeof initializeQualityChartControls === "function") initializeQualityChartControls();
    const complete = () => {
        if (form?.dataset.directoryUrl) initializeQualityMatrix();
        initializeQualityAnalysis(previous);
        if (!form?.dataset.directoryUrl) initializeQualityMatrix();
        if (document.querySelector("[data-quality-coverage]")) initializeQualityCoverage();
        if (document.querySelector("[data-quality-results]")) initializeQualityAuthorship();
        if (form) form.dataset.qualityReady = "1";
    };
    if (!form) {complete(); return;}
    initializeQualitySelection(form);
    if ((!qualityMetadata(form) && !form.dataset.metadataUrl) || form.hasAttribute("data-quality-loading")) return;
    form.setAttribute("data-quality-loading", "");
    const status = form.querySelector("[data-quality-load-status]");
    const retry = form.querySelector("[data-quality-retry]");
    const loading = form.dataset.loading || "Loading article statistics…";
    const failure = form.dataset.loadFailed || "Article filters could not load. Try again.";
    if (status) {status.textContent = loading; status.hidden = false;}
    if (retry) retry.hidden = true;
    // The visible author directory is small; its closed detail tables stay lazy.
    if (document.querySelector("[data-quality-results]")) initializeQualityAuthorship();
    let pending = false;
    async function load() {
        if (pending || !form.isConnected || form.dataset.qualityReady === "1") return;
        pending = true;
        form.dataset.qualityLoadState = "loading";
        if (status) status.textContent = loading;
        if (retry) retry.hidden = true;
        try {
            await loadQualityMetadata(form);
            if (!form.dataset.directoryUrl) await prepareCatalogRows(form);
            if (!form.isConnected) return;
            complete();
            form.dataset.qualityLoadState = "ready";
            if (status) status.hidden = true;
        } catch {
            if (!form.isConnected) return;
            form.dataset.qualityLoadState = "error";
            if (status) {status.textContent = failure; status.hidden = false;}
            if (retry) retry.hidden = false;
        } finally {pending = false;}
    }
    retry?.addEventListener("click", () => void load());
    // Two frames let the initial HTML and charts paint before catalog processing.
    if (qualityMetadata(form)) void load();
    else requestAnimationFrame(() => requestAnimationFrame(() => void load()));
}

/** Compare existing cell observations while leaving unknown values last. */
export function compareAnalysisRows(left, right, column, descending, locale) {
    const read = (row) => {
        const value = row.cells[column].dataset.sort;
        return value === undefined || value === "" ? null :
            [2, 3, 6, 7].includes(column) ? Number(value) : value;
    };
    return compareValues(read(left), read(right), descending, locale);
}

/** Read only explicit main-contributor and proven significant-contributor names. */
export function articleContributorRoles(row) {
    return {
        main: JSON.parse(row.dataset.mainAuthors || "[]"),
        mainLabels: JSON.parse(row.dataset.mainAuthorLabels || row.dataset.mainAuthors || "[]"),
        significant: JSON.parse(row.dataset.significantAuthors || "[]"),
    };
}

/** Use one comparison form for both Traditional and Simplified input. */
function foldedSearch(value, locale) {
    return value.normalize("NFKC").replace(/\p{Script=Han}/gu, character =>
        traditional[character] || character).toLocaleLowerCase(locale);
}

/** Compile a regex once per input change, or match literal text. */
export function searchMatcher(value, regex, locale, whole = false) {
    const query = value.trim();
    if (!query) return () => true;
    if (regex) {
        try {
            const pattern = new RegExp(query, "iu");
            return candidate => pattern.test(candidate);
        } catch (error) {
            if (error instanceof SyntaxError) return null;
            throw error;
        }
    }
    const needle = foldedSearch(query, locale);
    return candidate => {
        const text = foldedSearch(candidate, locale);
        return whole ? text === needle : text.includes(needle);
    };
}

/** Match an author only within the selected contribution type. */
export function contributorMatches(roles, author, role, locale) {
    if (!author.trim()) return true;
    return contributorsForRole(roles, role).some(searchMatcher(author, false, locale, true));
}

function contributorsForRole(roles, role) {
    return [...(roles[role] || []), ...(role === "main" ? roles.mainLabels || [] : [])];
}

/** Enhance the native table while preserving its escaped cells and links. */
export function initializeQualityAnalysis(previous = {}) {
    const host = document.querySelector("[data-quality-analysis]");
    if (!host || host.hasAttribute("data-analysis-enhanced")) return;
    host.setAttribute("data-analysis-enhanced", "");
    const form = document.querySelector("[data-quality-matrix]");
    const remote = Boolean(form?.dataset.directoryUrl);
    const rows = [...host.querySelectorAll("[data-analysis-row]"), ...(remote ? [] : catalogRows())];
    if (!remote) host.analysisRows = rows;
    const table = host.querySelector("table");
    const body = table.tBodies[0];
    const headings = [...table.querySelectorAll("thead th")];
    const search = host.querySelector("[data-analysis-search]");
    const regex = host.querySelector("[data-analysis-regex]");
    const regexError = host.querySelector("[data-analysis-regex-error]");
    const grade = host.querySelector("[data-analysis-grade-filter]");
    const importance = host.querySelector("[data-analysis-importance-filter]");
    const author = host.querySelector("[data-analysis-author]");
    const role = host.querySelector("[data-analysis-author-role]");
    const contributors = new Map(remote ? [] : rows.map(row => [row, articleContributorRoles(row)]));
    const suggestions = host.querySelector("#analysis-author-names");
    function showSuggestions(names) {
        if (!suggestions) return;
        suggestions.replaceChildren(...names.map(name => {const option = document.createElement("option"); option.value = name; return option;}));
    }
    function suggestContributors() {
        if (remote) return;
        showSuggestions([...new Set([...contributors.values()].flatMap(items =>
            items[role?.value === "significant" ? "significant" : "mainLabels"] || []))].sort());
    }
    const size = host.querySelector("[data-analysis-size]");
    const pager = host.querySelector("[data-analysis-pager]");
    const result = host.querySelector("[data-analysis-result-count]");
    const pageStatus = host.querySelector("[data-analysis-page-status]");
    const empty = host.querySelector("[data-analysis-no-matches]");
    const locale = document.documentElement.lang;
    search.value = previous.search ?? search.value;
    if (regex) regex.checked = previous.regex ?? regex.checked;
    grade.value = previous.grade ?? grade.value;
    importance.value = previous.importance ?? importance.value;
    if (author) author.value = previous.author ?? author.value;
    if (role) role.value = ["main", "significant"].includes(previous.role) ? previous.role : "main";
    suggestContributors();
    if (previous.size) size.value = previous.size;
    let column = previous.column ?? 4;
    let descending = previous.descending ?? true;
    let page = previous.page || 1;
    let pages = 1;
    let visiblePage = page, pending, debounce;
    const actions = ["first", "prev", "next", "last"].map((name) =>
        host.querySelector(`[data-analysis-${name}]`));

    function showPage(records, count, total, limit) {
        pages = Math.max(1, Math.ceil(count / limit));
        page = Math.min(page, pages);
        visiblePage = page;
        const start = (page - 1) * limit;
        host.dataset.analysisColumn = String(column);
        host.dataset.analysisDescending = String(descending);
        host.dataset.analysisPage = String(page);
        body.replaceChildren(...records.map((record, index) => {
            const row = articleElement(record);
            row.hidden = false;
            row.cells[0].textContent = String(start + index + 1);
            return row;
        }));
        result.textContent = host.dataset.resultCount
            .replace("{count}", groupedNumber(count)).replace("{total}", groupedNumber(total));
        pageStatus.textContent = host.dataset.pageStatus
            .replace("{start}", groupedNumber(count ? start + 1 : 0))
            .replace("{end}", groupedNumber(start + records.length))
            .replace("{total}", groupedNumber(count));
        empty.hidden = count !== 0;
        pager.hidden = false;
        updateQualityPageInput(pager, page, pages);
        actions[0].disabled = actions[1].disabled = page <= 1;
        actions[2].disabled = actions[3].disabled = page >= pages;
        headings.forEach((heading, index) => {
            if (index) heading.setAttribute("aria-sort", index === column ?
                (descending ? "descending" : "ascending") : "none");
        });
    }

    async function readPage(options) {
        const request = new AbortController();
        pending = request;
        table.setAttribute("aria-busy", "true");
        result.textContent = form.dataset.loadingPage;
        try {
            const response = await requestQualityPage(form, form.qualitySelection, options, request.signal);
            if (request.signal.aborted || !host.isConnected) return;
            if (response.regex_error) {
                regexError.hidden = false;
                showPage([], 0, form.qualityCoverage?.total ?? qualityMetadata(form).total, options.size);
                return;
            }
            showSuggestions(response.suggestions);
            page = response.page;
            showPage(directoryRows(qualityMetadata(form), response.rows), response.total, response.cohort, options.size);
        } catch {
            if (!request.signal.aborted && host.isConnected) {
                page = visiblePage;
                updateQualityPageInput(pager, page, pages);
                result.textContent = form.dataset.pageFailed;
            }
        } finally {
            if (pending === request) table.removeAttribute("aria-busy");
        }
    }

    /** Apply filters before ordering and pagination, retaining stable ties. */
    function render(typing = false) {
        clearTimeout(debounce);
        pending?.abort();
        const titleMatches = searchMatcher(search.value, regex?.checked, locale);
        const authorMatches = searchMatcher(author?.value || "", regex?.checked, locale, true);
        for (const [input, matcher] of [[search, titleMatches], [author, authorMatches]]) {
            if (matcher) input?.removeAttribute("aria-invalid");
            else input?.setAttribute("aria-invalid", "true");
        }
        if (regexError) regexError.hidden = Boolean(titleMatches && authorMatches);
        const roleName = role?.value || "main";
        if (remote) {
            if (!titleMatches || !authorMatches) {
                table.removeAttribute("aria-busy");
                showPage([], 0, form.qualityCoverage?.total ?? qualityMetadata(form).total, Number(size.value));
                return;
            }
            const options = {view: "articles", page, size: Number(size.value), column, descending,
                search: search.value, regex: !!regex?.checked, author: author?.value || "", role: roleName,
                grade: grade.value, importance: importance.value};
            if (typing) debounce = setTimeout(() => void readPage(options), 180);
            else void readPage(options);
            return;
        }
        const selected = rows.filter((row) =>
            (row.dataset.cohort !== "0") &&
            authorMatches && (!author?.value.trim() || contributorsForRole(contributors.get(row), roleName).some(authorMatches)) &&
            (!grade.value || row.dataset.grade === grade.value) &&
            (!importance.value || row.dataset.importance === importance.value) &&
            titleMatches && (titleMatches(row.dataset.title || "") || titleMatches(row.cells[1].dataset.sort || "")));
        selected.sort((left, right) =>
            compareAnalysisRows(left, right, column, descending, locale));
        const limit = size.value === "all" ? Math.max(1, selected.length) : Number(size.value);
        pages = Math.max(1, Math.ceil(selected.length / limit));
        page = Math.min(page, pages);
        const start = (page - 1) * limit;
        showPage(selected.slice(start, start + limit), selected.length, rows.length, limit);
    }
    [search, regex, grade, importance, size, author, role].filter(Boolean).forEach((control) => {
        control.addEventListener(control === search || control === author ? "input" : "change", () => {
            if (control === role) suggestContributors();
            page = 1;
            render(control === search || control === author);
        });
    });
    initializeQualityPageInput(pager, target => { page = target; render(); });
    headings.forEach((heading, index) => {
        if (!index) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ui-table__table__sort-button";
        button.textContent = heading.textContent;
        button.title = host.dataset.sortCaption.replace("{caption}", heading.textContent);
        button.addEventListener("click", () => {
            descending = column === index ? !descending : false;
            column = index;
            page = 1;
            render();
        });
        heading.replaceChildren(button);
    });
    actions.forEach((button, index) => button.addEventListener("click", () => {
        page = [1, page - 1, page + 1, pages][index];
        render();
    }));
    host.querySelector("[data-analysis-reset]").addEventListener("click", () => {
        search.value = grade.value = importance.value = "";
        if (regex) regex.checked = false;
        if (author) author.value = "";
        if (role) role.value = "main";
        suggestContributors();
        page = 1;
        render();
        search.focus();
    });
    const cohortChanged = () => {
        if (!host.isConnected) {
            document.removeEventListener("quality-cohort-change", cohortChanged);
            return;
        }
        page = 1;
        render();
    };
    document.addEventListener("quality-cohort-change", cohortChanged);
    initializeChartArticles(rows, form);
    host.querySelector("[data-analysis-controls]").hidden = false;
    if (remote && !Object.keys(previous).length) {
        const {total} = qualityMetadata(form);
        const limit = Number(size.value);
        showPage(rows.slice(0, limit), total, total, limit);
    } else render();
}

/** Select a chart's saved cohort independently of directory filters. */
export function chartArticleMatches(row, selection) {
    return row.dataset.cohort !== "0" && row.dataset[selection.chartGroup] === selection.chartValue &&
        (!selection.chartYear || row.dataset.year === selection.chartYear) &&
        (!selection.chartMeasured || row.dataset.measured === "1");
}

const chartArticleColumns = [0, 1, 2, 3, 4, 6, 7];

/** Sort chart-dialog columns against their original article observations. */
export function orderChartArticles(rows, column, descending, locale) {
    const sourceColumn = chartArticleColumns[column];
    return [...rows].sort((left, right) => compareAnalysisRows(left, right, sourceColumn, descending, locale));
}

/** Fill one accessible dialog from already rendered, escaped article cells. */
function initializeChartArticles(rows, form) {
    const dialog = document.getElementById("analysis-chart-articles");
    if (!dialog || typeof dialog.showModal !== "function") return;
    const body = dialog.querySelector("[data-chart-article-rows]");
    const count = dialog.querySelector("[data-chart-article-count]");
    const heading = document.getElementById("analysis-chart-articles-heading");
    const pager = dialog.querySelector("[data-chart-pager]");
    const sizeControl = pager.querySelector("[data-chart-size]");
    const headings = [...dialog.querySelectorAll("thead th")];
    const sortCaption = document.querySelector("[data-quality-analysis]")?.dataset.sortCaption;
    const remote = Boolean(form?.dataset.directoryUrl);
    let selected = [], page = 1, total = 0, chart, pending;
    let column = 4, descending = true;
    const pageCount = () => Math.max(1, Math.ceil(total / Number(sizeControl.value)));
    const actions = {first: () => 1, prev: () => page - 1, next: () => page + 1, last: pageCount};
    function showPage(ordered) {
        const size = Number(sizeControl.value), pages = pageCount();
        page = Math.max(1, Math.min(page, pages));
        const start = (page - 1) * size;
        body.replaceChildren(...ordered.map((source, index) => {
            const row = document.createElement("tr");
            row.dataset.chartArticle = source.dataset.title;
            const original = articleElement(source);
            for (const column of chartArticleColumns) {
                const cell = original.cells[column].cloneNode(true);
                if (!column) cell.textContent = String(start + index + 1);
                row.append(cell);
            }
            return row;
        }));
        pager.querySelector("[data-chart-page-status]").textContent = pager.dataset.pageStatus
            .replace("{start}", groupedNumber(total ? start + 1 : 0))
            .replace("{end}", groupedNumber(start + ordered.length))
            .replace("{total}", groupedNumber(total));
        updateQualityPageInput(pager, page, pages);
        for (const key of Object.keys(actions)) pager.querySelector(`[data-chart-${key}]`).disabled = ["first", "prev"].includes(key) ? page === 1 : page === pages;
        headings.forEach((heading, index) => {
            if (index) heading.setAttribute("aria-sort", index === column ? (descending ? "descending" : "ascending") : "none");
        });
        count.textContent = count.dataset.label.replace("{count}", groupedNumber(total));
    }
    async function render() {
        const size = Number(sizeControl.value);
        if (!remote) {
            page = Math.max(1, Math.min(page, pageCount()));
            const start = (page - 1) * size;
            const ordered = orderChartArticles(selected, column, descending, document.documentElement.lang);
            showPage(ordered.slice(start, start + size));
            return;
        }
        pending?.abort();
        const request = new AbortController();
        pending = request;
        count.textContent = form.dataset.loadingPage;
        try {
            const response = await requestQualityPage(form, form.qualitySelection, {
                view: "chart", page, size, column: chartArticleColumns[column], descending,
                group: chart.chartGroup, value: chart.chartValue,
                ...(chart.chartYear ? {year: Number(chart.chartYear)} : {}),
                measured: !!chart.chartMeasured,
            }, request.signal);
            if (request.signal.aborted || !dialog.open) return;
            total = response.total;
            page = response.page;
            showPage(directoryRows(qualityMetadata(form), response.rows));
        } catch {
            if (!request.signal.aborted && dialog.open) count.textContent = form.dataset.pageFailed;
        }
    }
    headings.forEach((heading, index) => {
        if (!index) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ui-table__table__sort-button";
        button.textContent = heading.textContent;
        button.title = sortCaption?.replace("{caption}", heading.textContent) || heading.textContent;
        button.addEventListener("click", () => {
            descending = column === index ? !descending : false;
            column = index;
            page = 1;
            render();
        });
        heading.replaceChildren(button);
    });
    for (const [key, destination] of Object.entries(actions)) pager.querySelector(`[data-chart-${key}]`).addEventListener("click", () => {page = destination(); render();});
    initializeQualityPageInput(pager, target => { page = target; render(); });
    sizeControl.addEventListener("change", () => {page = 1; render();});
    const openChart = event => {
        if (!dialog.isConnected) {
            document.removeEventListener("click", openChart);
            return;
        }
        const link = event.target.closest?.("[data-chart-group]");
        if (!link || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        event.stopPropagation();
        chart = link.dataset;
        if (remote) {
            body.replaceChildren();
            pager.querySelector("[data-chart-page-status]").textContent = "";
            for (const key of Object.keys(actions)) pager.querySelector(`[data-chart-${key}]`).disabled = true;
        } else {
            selected = rows.filter(row => chartArticleMatches(row, chart));
            total = selected.length;
        }
        page = 1;
        column = 4;
        descending = true;
        heading.textContent = link.dataset.chartLabel;
        link.focus();
        if (!dialog.open) dialog.showModal();
        void render();
    };
    if (remote) dialog.addEventListener("close", () => {
        pending?.abort();
        body.replaceChildren();
    });
    document.addEventListener("click", openChart);
    const activateChart = event => {
        if (!dialog.isConnected) {
            document.removeEventListener("keydown", activateChart);
            return;
        }
        const link = event.target.closest?.("[data-chart-group]");
        if (!link || event.key !== " ") return;
        event.preventDefault();
        link.dispatchEvent(new MouseEvent("click", {bubbles: true}));
    };
    document.addEventListener("keydown", activateChart);
}

/** Retain the current directory selection across a global B-Class update. */
function analysisState() {
    const host = document.querySelector("[data-quality-analysis]");
    if (!host) return {};
    const value = name => host.querySelector(`[data-analysis-${name}]`)?.value;
    return {
        search: value("search"), grade: value("grade-filter"),
        regex: host.querySelector("[data-analysis-regex]")?.checked,
        importance: value("importance-filter"), size: value("size"),
        author: value("author"), role: value("author-role"),
        column: Number(host.dataset.analysisColumn || 4),
        descending: host.dataset.analysisDescending !== "false",
        page: Number(host.dataset.analysisPage || 1),
    };
}

document.addEventListener?.("quality-charts-replaced", () => initializeQualityChartControls());
initializeQualityPage();
const basis = document.querySelector("[data-authorship-basis]");
basis?.elements.namedItem("listing_authors")?.addEventListener("change", () => basis.requestSubmit());
