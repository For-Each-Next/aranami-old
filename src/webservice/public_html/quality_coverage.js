/** Show evidence coverage and bounded lists for the selected article cohort. */
import { qualityMetadata, requestQualityPage } from "./quality_matrix.js";

let cohortListenerInstalled = false;

/** Preserve measured zeroes and acquired attribution without named editors. */
export function articleCoverage(record) {
    const article = record.article;
    return {
        authorship: article ? article.authorship?.available === true : record.dataset.coverageAuthorship === "1",
        dates: article ? Boolean(article.listed_date) : Boolean(record.dataset.year),
        length: article ? article.prose_characters !== null && article.prose_characters !== undefined : record.dataset.measured === "1",
    };
}

/** Count only matrix-selected records, independently of directory searching. */
export function coverageSummary(records) {
    const counts = {total: 0, authorship: 0, dates: 0, length: 0};
    for (const record of records) {
        if (record.dataset.cohort === "0") continue;
        counts.total++;
        for (const [key, acquired] of Object.entries(articleCoverage(record))) counts[key] += Number(acquired);
    }
    return counts;
}

/** Include either source's selected grade, retaining category-only articles. */
export function comparisonSelection(comparison, grades) {
    if (!comparison?.available) return [];
    return (comparison.rows || []).filter(row =>
        grades.has(row.pageassessments_grade) || row.category_grades.some(grade => grades.has(grade)));
}

/** Reuse lightweight catalog records and keep only one dialog page in the DOM. */
export function initializeQualityCoverage() {
    const host = document.querySelector("[data-quality-coverage]");
    const dialog = document.getElementById("analysis-coverage-dialog");
    if (!host || !dialog || host.coverageRefresh) return;
    const labels = JSON.parse(host.dataset.coverageLabels);
    const body = dialog.querySelector("[data-coverage-rows]");
    const empty = dialog.querySelector("[data-coverage-empty]");
    const status = dialog.querySelector("[data-coverage-page-status]");
    const table = body.closest("table");
    const pager = status.closest("nav");
    const size = pager.querySelector("select");
    const form = document.querySelector("[data-quality-matrix]");
    const remote = Boolean(form?.dataset.directoryUrl);
    let selected = [], page = 1, total = 0, kind, opener, pending;
    const number = value => value.toLocaleString(document.documentElement.lang);
    const records = () => document.querySelector("[data-quality-analysis]")?.analysisRows || [];
    const metadata = () => qualityMetadata();
    const comparison = () => metadata()?.assessment_comparison ||
        (host.dataset.coverageComparison ? JSON.parse(host.dataset.coverageComparison) : null);
    const grades = () => {
        const form = document.querySelector("[data-quality-matrix]");
        return new Set(form ? [...form.querySelectorAll("[data-matrix-cell]")]
            .filter(input => input.checked).map(input => input.dataset.grade) : records().map(row => row.dataset.grade));
    };
    const node = (tag, text) => {
        const element = document.createElement(tag);
        if (text !== undefined) element.textContent = String(text);
        return element;
    };
    const gradeLabel = grade => metadata()?.grades.find(item => item.value === grade)?.article_label || grade || "—";

    /** Retain references only to the currently requested missing-page list. */
    function chooseRows() {
        if (remote) return;
        selected = kind === "total" ? comparisonSelection(comparison(), grades()) : records().filter(record =>
            record.dataset.cohort !== "0" && !articleCoverage(record)[kind]);
        total = selected.length;
    }

    /** Replace the requested page and retain its navigation controls. */
    function showPage(visible, available) {
        const limit = Number(size?.value || 50);
        const pages = Math.max(1, Math.ceil(total / limit));
        const start = (page - 1) * limit;
        body.replaceChildren(...visible.map((record, index) => {
            const row = node("tr"), titleCell = node("td");
            const title = record.title ?? record.article?.title ?? record.dataset.title;
            const label = record.article?.title_label ?? title.replaceAll("_", " ");
            const link = node("a", label);
            link.href = `https://zh.wikipedia.org/wiki/${encodeURIComponent(title.replaceAll(" ", "_"))}`;
            titleCell.append(link);
            row.append(node("td", number(start + index + 1)), titleCell);
            if (kind === "total") row.append(
                node("td", record.category_grades.map(gradeLabel).join(" / ") || "—"),
                node("td", gradeLabel(record.pageassessments_grade)),
                node("td", labels[record.kind] || record.kind));
            return row;
        }));
        for (const heading of dialog.querySelectorAll("[data-coverage-comparison-column]")) heading.hidden = kind !== "total";
        empty.hidden = total > 0;
        empty.textContent = kind === "total" && !available ? labels.comparison_unavailable : labels.no_missing;
        table.hidden = total === 0;
        status.textContent = status.dataset.template.replace("{start}", number(total ? start + 1 : 0))
            .replace("{end}", number(start + visible.length)).replace("{total}", number(total));
        for (const button of dialog.querySelectorAll("[data-coverage-page]")) button.disabled =
            ["first", "previous"].includes(button.dataset.coveragePage) ? page === 1 : page === pages;
    }

    async function render() {
        const limit = Number(size?.value || 50);
        if (!remote) {
            page = Math.max(1, Math.min(page, Math.ceil(total / limit)));
            const start = (page - 1) * limit;
            showPage(selected.slice(start, start + limit), comparison()?.available);
            return;
        }
        pending?.abort();
        const request = new AbortController();
        pending = request;
        status.textContent = form.dataset.loadingPage;
        try {
            const response = await requestQualityPage(form, form.qualitySelection,
                {view: "coverage", value: kind, page, size: limit}, request.signal);
            if (request.signal.aborted || !dialog.open) return;
            total = response.total;
            page = response.page;
            showPage(response.rows, response.available);
        } catch {
            if (!request.signal.aborted && dialog.open) status.textContent = form.dataset.pageFailed;
        }
    }

    size?.addEventListener("change", () => { page = 1; render(); });
    host.coverageRefresh = () => {
        const counts = remote ? form.qualityCoverage : coverageSummary(records());
        if (counts) {
            for (const element of host.querySelectorAll("[data-coverage-count]")) element.textContent = number(counts[element.dataset.coverageCount]);
        }
        if (dialog.open) {chooseRows(); page = 1; render();}
    };
    host.addEventListener("click", event => {
        const control = event.target.closest("[data-coverage-open]");
        if (!control || event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button > 0 || typeof dialog.showModal !== "function") return;
        event.preventDefault();
        kind = control.dataset.coverageOpen;
        opener = control;
        dialog.querySelector(".ui-dialog__header__title").textContent = labels[kind === "total" ? "comparison" : `missing_${kind}`];
        chooseRows();
        page = 1;
        dialog.showModal();
        void render();
    });
    dialog.addEventListener("click", event => {
        const control = event.target.closest("[data-coverage-page]");
        if (!control) return;
        const target = control.dataset.coveragePage;
        page = target === "first" ? 1 : target === "last" ? Math.ceil(total / Number(size?.value || 50)) : page + (target === "next" ? 1 : -1);
        render();
        dialog.querySelector(".ui-dialog__body")?.scrollTo(0, 0);
    });
    dialog.addEventListener("close", () => {
        pending?.abort();
        selected = []; body.replaceChildren();
        const returnFocus = opener;
        opener = kind = undefined;
        if (returnFocus?.isConnected) returnFocus.focus();
    });
    if (!cohortListenerInstalled) {
        document.addEventListener("quality-cohort-change", () => document.querySelector("[data-quality-coverage]")?.coverageRefresh?.());
        cohortListenerInstalled = true;
    }
    host.coverageRefresh();
}
