/** Combine saved matrix statistics and keep every report view in one cohort. */

const metadataRequests = new WeakMap();
const directoryPages = new WeakMap();

/** Reuse the parsed catalog for both article controls and matrix filters. */
export function qualityMetadata(form = document.querySelector("[data-quality-matrix]")) {
    if (!form) return null;
    if (!form.qualityMetadata && form.dataset.metadata) {
        form.qualityMetadata = JSON.parse(form.dataset.metadata);
        form.qualityMetadata.authorshipIcon = form.dataset.authorshipIcon;
    }
    return form.qualityMetadata || null;
}

/** Fetch a saved catalog once, allowing a fresh attempt after any failure. */
export function loadQualityMetadata(form) {
    const saved = qualityMetadata(form);
    if (saved) return Promise.resolve(saved);
    if (metadataRequests.has(form)) return metadataRequests.get(form);
    const request = (async () => {
        const url = new URL(form.dataset.metadataUrl, location.href);
        if (url.origin !== location.origin) throw new Error("Invalid quality catalog URL");
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 30000);
        try {
            const response = await fetch(url, {
                credentials: "same-origin", redirect: "error", signal: controller.signal,
                headers: {Accept: "application/json"},
            });
            if (!response.ok || (response.url && new URL(response.url).origin !== location.origin) ||
                    !response.headers.get("content-type")?.startsWith("application/json"))
                throw new Error("Quality catalog unavailable");
            const data = await response.json();
            if (!data || ![data.cells, data.grades, data.importance].every(Array.isArray) ||
                    !data.labels || typeof data.labels !== "object" ||
                    (form.dataset.directoryUrl
                        ? !Number.isInteger(data.total)
                        : !Array.isArray(data.extra) || !data.extra.every(row => Array.isArray(row) && row.length >= 13)))
                throw new Error("Invalid quality catalog");
            data.authorshipIcon = form.dataset.authorshipIcon;
            form.qualityMetadata = data;
            return data;
        } finally {
            clearTimeout(timeout);
        }
    })();
    metadataRequests.set(form, request);
    request.catch(() => metadataRequests.delete(form));
    return request;
}

/** Read one view of the confirmed selection and retain at most three pages. */
export async function requestQualityPage(form, selection, options, signal) {
    const url = new URL(form.dataset.directoryUrl, location.href);
    if (url.origin !== location.origin) throw new Error("Invalid article directory URL");
    const query = JSON.stringify({
        cells: [...selection.chosen],
        first: selection.firstYear, last: selection.lastYear, unknown: selection.includeUnknown,
        ...options,
    });
    const encoded = btoa(String.fromCharCode(...new TextEncoder().encode(query)))
        .replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
    url.searchParams.set("q", encoded);
    if (!directoryPages.has(form)) directoryPages.set(form, new Map());
    const cache = directoryPages.get(form);
    if (cache.has(encoded)) {
        const saved = cache.get(encoded);
        cache.delete(encoded);
        cache.set(encoded, saved);
        return saved;
    }
    let response;
    const timeout = AbortSignal.timeout(15000);
    const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
    for (const delay of [0, 125, 250]) {
        if (delay) await new Promise(resolve => setTimeout(resolve, delay));
        response = await fetch(url, {
            credentials: "same-origin", redirect: "error", signal: requestSignal,
            headers: {Accept: "application/json"},
        });
        if (response.status !== 429) break;
    }
    if ((response.url && new URL(response.url).origin !== location.origin) ||
            !response.headers.get("content-type")?.startsWith("application/json"))
        throw new Error("Invalid article directory response");
    if (response.status === 422) return {regex_error: true};
    if (!response.ok) throw new Error("Article directory unavailable");
    const result = await response.json();
    if (options.view !== "summary") {
        if (!Array.isArray(result.rows) || result.rows.length > options.size ||
                !Number.isInteger(result.page) || !Number.isInteger(result.total))
            throw new Error("Invalid article directory page");
        cache.set(encoded, result);
        if (cache.size > 3) cache.delete(cache.keys().next().value);
    }
    return result;
}

/** Include unknown dates independently of the inclusive year range. */
export function yearSelected(year, from, to, unknown) {
    return year === null || year === "" ? unknown : Number(year) >= Math.max(2009, from) && Number(year) <= to;
}

/** Use the same confirmed grade, importance and year in every browse view. */
export function matchesQualitySelection(selection, grade, importance, year) {
    return selection.chosen.has(grade + ":" + importance)
        && yearSelected(year, selection.firstYear, selection.lastYear, selection.includeUnknown);
}

/** Recover an exact linear quantile from a saved, counted length histogram. */
export function histogramQuantile(histogram, probability) {
    const values = [...histogram].sort((a, b) => a[0] - b[0]);
    const count = values.reduce((sum, pair) => sum + pair[1], 0);
    if (!count) return null;
    const position = (count - 1) * probability;
    const at = index => {
        let offset = 0;
        for (const [value, frequency] of values) {
            offset += frequency;
            if (index < offset) return value;
        }
        return null;
    };
    const low = at(Math.floor(position));
    return low + (at(Math.ceil(position)) - low) * (position % 1);
}

/** Add prepared cells, retaining missing length measurements separately. */
export function combineCells(cells) {
    const histogram = new Map();
    const points = new Map();
    let pages = 0, measured = 0;
    for (const cell of cells) {
        pages += cell.pages;
        measured += cell.measured;
        for (const item of cell.histogram) histogram.set(item.value, (histogram.get(item.value) || 0) + item.count);
        for (const item of cell.density) points.set(item.position, (points.get(item.position) || 0) + item.density);
    }
    const peakDensity = Math.max(0, ...points.values()) || 1;
    const observed = [...histogram].filter(([, count]) => count > 0).map(([value]) => value);
    const observedCount = observed.reduce((sum, value) => sum + histogram.get(value), 0);
    return {
        pages, measured,
        mean: observedCount ? observed.reduce((sum, value) => sum + value * histogram.get(value), 0) / observedCount : null,
        minimum: observed.length ? Math.min(...observed) : null,
        maximum: observed.length ? Math.max(...observed) : null,
        quantiles: [.025, .16, .5, .84, .975].map(p => histogramQuantile(histogram, p)),
        quartiles: [.25, .75].map(p => histogramQuantile(histogram, p)),
        density: [...points].sort((a, b) => a[0] - b[0]).map(([x, y]) => [x, y / peakDensity]),
    };
}

/** Use every observed catalog length, excluding empty histogram entries. */
export function proseLengthMaximum(cells) {
    let maximum = 25000;
    for (const cell of cells) {
        for (const item of cell.histogram) {
            if (item.count > 0) maximum = Math.max(maximum, item.value);
        }
    }
    return maximum;
}

/** Reserve 90% for 0–25,000 characters, then logarithmically reach the shared maximum. */
export function proseLengthPosition(characters, maximum) {
    if (characters <= 25000) return Math.max(0, characters / 25000 * 900);
    if (maximum <= 25000) return 900;
    return Math.min(1000, 900 + 100 * Math.log(characters / 25000) / Math.log(maximum / 25000));
}

/** Round prose measurements to two significant digits with integer labels. */
function proseLengthLabel(value) {
    if (value === null) return "—";
    const step = value > 0 ? 10 ** Math.max(0, Math.floor(Math.log10(value)) - 1) : 1;
    return (Math.round(value / step) * step).toLocaleString("en-US", {maximumFractionDigits: 0});
}

/** Give each percentile mark its own localized native tooltip. */
export function violinMarkerTitle(kind, value, labels) {
    const names = {minimum: "Minimum", p25: "Lower quartile", p50: "Median", p75: "Upper quartile", maximum: "Maximum", mean: "Mean"};
    const template = labels[`violin_${kind}`] || `${names[kind]}: {value} characters`;
    return template.replaceAll("{value}", proseLengthLabel(value));
}

/** Keep article counts exact while rounding the five length statistics for display. */
export function violinSummary(statistics, template) {
    const values = {
        pages: statistics.pages.toLocaleString("en-US"), measured: statistics.measured.toLocaleString("en-US"),
        minimum: proseLengthLabel(statistics.minimum), maximum: proseLengthLabel(statistics.maximum),
        p25: proseLengthLabel(statistics.quartiles[0]), p50: proseLengthLabel(statistics.quantiles[2]), p75: proseLengthLabel(statistics.quartiles[1]),
    };
    return template.replace(/\{(pages|measured|minimum|p25|p50|p75|maximum)\}/g, (_, key) => values[key]);
}

/** Keep year-table columns selected and the legend limited to plotted categories. */
export function qualityYearSummary(selected, grades, firstYear, lastYear) {
    const counts = new Map();
    for (const { year, grade, pages } of selected) {
        if (year === null) continue;
        if (!counts.has(year)) counts.set(year, new Map());
        const byGrade = counts.get(year);
        byGrade.set(grade, (byGrade.get(grade) ?? 0) + pages);
    }
    const years = [];
    for (let year = Math.max(2009, firstYear); year <= lastYear; year++) {
        const totals = grades.map(grade => counts.get(year)?.get(grade.value) ?? 0);
        years.push({
            year,
            pages: totals.reduce((sum, count) => sum + count, 0),
            grades: totals,
        });
    }
    return {years, legend: grades.filter((_, index) => years.some(year => year.grades[index] > 0))};
}

const svgNamespace = "http://www.w3.org/2000/svg";
function svgNode(tag, attributes = {}, text) {
    const node = document.createElementNS(svgNamespace, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    if (text !== undefined) node.textContent = String(text);
    return node;
}
function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = String(text);
    if (className) element.className = className;
    return element;
}
function chartLink(group, value, label, year, svg = false) {
    const link = svg ? svgNode("a") : node("a");
    link.setAttribute("href", "#analysis-articles");
    link.setAttribute("aria-haspopup", "dialog");
    link.setAttribute("aria-controls", "analysis-chart-articles");
    if (svg) link.setAttribute("tabindex", "0");
    else link.textContent = label;
    Object.assign(link.dataset, {chartGroup: group, chartValue: value, chartLabel: label});
    if (year !== undefined) link.dataset.chartYear = String(year);
    return link;
}
const format = value => value === null ? "—" : Math.round(value).toLocaleString(document.documentElement.lang);

/** Label an interactive mark and make it open its exact article cohort. */
function plotLink(group, option, mark, description, year) {
    const link = chartLink(group, option.value, option.label, year, true);
    link.setAttribute("aria-label", description);
    link.append(svgNode("title", {}, description), mark);
    return link;
}

/** Draw an assessment distribution, including empty and single-group selections. */
function pieFigure(entries, group, total, caption) {
    const svg = svgNode("svg", {
        viewBox: "0 0 240 240", class: "analysis-pie", role: "group",
        "aria-label": caption, "data-analysis-pie": group === "grade" ? "class" : group,
        "data-chart-renderer": "browser",
    });
    const center = {cx: 120, cy: 120, r: 112};
    if (!total) svg.append(svgNode("circle", {...center, class: "analysis-pie-empty"}));
    let angle = -Math.PI / 2;
    const point = theta => [120 + center.r * Math.cos(theta), 120 + center.r * Math.sin(theta)].join(" ");
    for (const {option, summary} of entries) {
        const share = summary.pages / total;
        const next = angle + 2 * Math.PI * share;
        const style = {class: "analysis-pie-slice", fill: option.color};
        const mark = share === 1
            ? svgNode("circle", {...center, ...style})
            : svgNode("path", {
                ...style,
                d: `M 120 120 L ${point(angle)} A 112 112 0 ${share > .5 ? 1 : 0} 1 ${point(next)} Z`,
            });
        const description = `${option.label} · ${format(summary.pages)} (${(share * 100).toFixed(1)}%)`;
        svg.append(plotLink(group, option, mark, description));
        angle = next;
    }
    return svg;
}

/** Draw the saved density with exact extrema, quartiles, median and mean. */
function violinFigure(summary, group, option, labels, maximum) {
    const caption = option.label + " · " + violinSummary(summary, labels.violin_summary);
    const svg = svgNode("svg", {
        viewBox: "0 0 1020 44", preserveAspectRatio: "none", role: "group",
        class: "analysis-mini-violin", "aria-label": caption,
        "data-analysis-violin": option.value, "data-chart-renderer": "browser",
    });
    const plot = svgNode("g");
    const x = value => 10 + proseLengthPosition(value, maximum);
    plot.append(svgNode("line", {x1: 10, x2: 1010, y1: 22, y2: 22, class: "analysis-violin-track"}));
    const points = [...summary.density.map(([value, density]) => [x(value), 22 - 18 * density]),
        ...summary.density.toReversed().map(([value, density]) => [x(value), 22 + 18 * density])];
    if (points.length) {
        plot.append(svgNode("polygon", {
            points: points.map(point => point.join(",")).join(" "),
            class: "analysis-violin-density", fill: option.color,
        }));
    }
    for (const [kind, value] of Object.entries({
        minimum: summary.minimum, p25: summary.quartiles[0], p50: summary.quantiles[2],
        p75: summary.quartiles[1], maximum: summary.maximum, mean: summary.mean,
    })) {
        if (value === null) continue;
        const position = x(value);
        const attributes = {"data-statistic": kind, "data-value": value};
        let mark;
        if (kind === "mean") {
            mark = svgNode("g", {
                ...attributes, class: "analysis-violin-mean",
                "data-mean-x": proseLengthPosition(value, maximum),
            });
            for (const direction of [-1, 1]) {
                mark.append(svgNode("line", {x1: position - 14, x2: position + 14, y1: 22 - 6 * direction, y2: 22 + 6 * direction}));
            }
        } else if (kind === "p25" || kind === "p75") {
            mark = svgNode("line", {
                ...attributes, class: "analysis-violin-quartile", "data-percentile": kind.slice(1),
                x1: position, x2: position, y1: 22, y2: 22,
            });
        } else {
            mark = svgNode("line", {
                ...attributes, class: kind === "p50" ? "analysis-violin-median" : "analysis-violin-extreme",
                x1: position, x2: position, y1: 15, y2: 29,
                ...(kind === "p50" ? {} : {"data-extreme": kind}),
            });
        }
        mark.append(svgNode("title", {}, violinMarkerTitle(kind, value, labels)));
        plot.append(mark);
    }
    const link = plotLink(group, option, plot, caption);
    link.dataset.chartMeasured = "1";
    svg.append(link);
    return svg;
}

/** Draw summed annual counts and link each stacked bar to its articles. */
function annualFigure(years, grades, caption) {
    const width = Math.max(420, 54 + years.length * 44);
    const svg = svgNode("svg", {
        viewBox: `0 0 ${width} 300`, width, height: 300, class: "analysis-year-columns",
        role: "group", "aria-label": caption, "data-chart-renderer": "browser",
    });
    const base = 260, left = 48, step = (width - left - 6) / years.length;
    const interval = Math.max(1, Math.ceil(Math.max(0, ...years.map(year => year.pages)) / 5));
    const height = count => 216 * count / (interval * 5);
    for (let tick = 0; tick <= 5; tick++) {
        const count = tick * interval, y = base - height(count);
        svg.append(svgNode("line", {x1: left, x2: width - 6, y1: y, y2: y, class: "analysis-year-grid"}),
            svgNode("text", {x: left - 6, y, "text-anchor": "end", "dominant-baseline": "middle", class: "analysis-axis-label"}, format(count)));
    }
    for (const [index, year] of years.entries()) {
        const x = left + step * (index + .5);
        let bottom = base;
        for (const [column, count] of year.grades.entries()) {
            if (!count) continue;
            const option = grades[column], barHeight = height(count);
            bottom -= barHeight;
            const mark = svgNode("rect", {x: x - step * .36, y: bottom, width: step * .72, height: barHeight, fill: option.color});
            svg.append(plotLink("grade", option, mark, `${year.year} · ${option.label} · ${format(count)}`, year.year));
        }
        svg.append(svgNode("text", {x, y: 280, "text-anchor": "middle", class: "analysis-axis-label"}, year.year));
        if (year.pages) svg.append(svgNode("text", {
            x, y: bottom - 5, "text-anchor": "middle", class: "analysis-column-total",
        }, format(year.pages)));
    }
    return svg;
}

/** Draw the default figures directly from the prepared overview. */
export function initializeQualityFigures(form) {
    if (!form?.qualityOverview) return;
    const {analysis, labels} = form.qualityOverview;
    delete form.qualityOverview;
    for (const [kind, group, rows] of [
        ["grades", "grade", analysis.grades],
        ["importance", "importance", analysis.importance_totals],
    ]) {
        const host = document.querySelector('[data-quality-chart="' + kind + '"]');
        if (!host) continue;
        const entries = rows.filter(row => row.pages > 0).map(row => ({
            option: {value: row[group], color: row.color, label: row.label},
            summary: {pages: row.pages},
        }));
        const total = entries.reduce((sum, entry) => sum + entry.summary.pages, 0);
        host.replaceChildren(pieFigure(entries, group, total, host.dataset.chartCaption));
        const lengths = new Map(rows.map(row => [row[group], row.length]));
        for (const cell of host.closest("figure").querySelectorAll("[data-quality-length]")) {
            const value = cell.dataset.qualityLength.slice(group.length + 1);
            const saved = lengths.get(value);
            if (!saved) continue;
            const summary = {
                pages: saved.pages, measured: saved.measured,
                minimum: saved.extrema.find(mark => mark.kind === "minimum")?.value ?? null,
                maximum: saved.extrema.find(mark => mark.kind === "maximum")?.value ?? null,
                mean: saved.mean ?? null, quantiles: [null, null, saved.median_characters ?? null],
                quartiles: [25, 75].map(percentile =>
                    saved.quartiles.find(mark => mark.percentile === percentile)?.value ?? null),
                density: (saved.density || []).map(({position, density}) => [position, density]),
            };
            const option = {value, label: saved.label, color: saved.color};
            cell.replaceChildren(violinFigure(summary, group, option, labels, analysis.length_scale_maximum));
        }
    }
    const host = document.querySelector('[data-quality-chart="years"]');
    if (!host) return;
    const grades = analysis.year_table_grades;
    const years = analysis.years.map(({year, pages, grades: counts}) => ({
        year, pages, grades: grades.map(grade => counts[grade.value] ?? 0),
    }));
    host.replaceChildren(annualFigure(years, grades, host.dataset.chartCaption));
}

const catalogRecords = new WeakMap();
const catalogPreparation = new WeakMap();
const catalogFields = ["page_id", "title", "grade", "importance", "listed_date", "listed_oldid", "prose_characters", "source_bytes", "authors", "title_label", "date_label", "authorship", "review_url", "main_contributors"];

/** Build one light sortable record without creating table elements. */
function catalogRecord(values, data, gradeOrder, importanceOrder) {
    const article = Object.fromEntries(catalogFields.map((key, index) => [key, values[index]]));
    return {
        article, metadata: data,
        dataset: {pageId: String(article.page_id), title: article.title, grade: article.grade, importance: article.importance, year: article.listed_date?.slice(0, 4) || "", measured: article.prose_characters === null ? "0" : "1", cohort: "0", mainAuthors: JSON.stringify(article.authorship?.available === true ? article.authors || [] : []), mainAuthorLabels: JSON.stringify(article.authorship?.available === true ? (article.main_contributors || []).map(author => author.label) : []), significantAuthors: JSON.stringify(article.authorship?.available === true ? article.authorship.editors.map(editor => editor.name) : [])},
        cells: [null, article.title_label, gradeOrder.get(article.grade) ?? -1, importanceOrder.get(article.importance) ?? -1, article.listed_date, (article.main_contributors || []).map(author => author.label).join(", "), article.prose_characters, article.source_bytes].map(value => ({dataset: {sort: value === null ? "" : String(value)}, textContent: value === null ? "" : String(value)})),
    };
}

/** Prepare catalog records in bounded batches while native controls remain responsive. */
export function prepareCatalogRows(form) {
    const data = qualityMetadata(form);
    if (!data) return Promise.resolve([]);
    if (catalogRecords.has(data)) return Promise.resolve(catalogRecords.get(data));
    if (catalogPreparation.has(data)) return catalogPreparation.get(data);
    const request = (async () => {
        const rows = [], extra = data.extra || [];
        const gradeOrder = new Map(data.grades.map((item, index) => [item.value, item.order ?? index]));
        const importanceOrder = new Map(data.importance.map((item, index) => [item.value, item.order ?? index]));
        for (let start = 0; start < extra.length; start += 256) {
            await new Promise(resolve => setTimeout(resolve, 0));
            if (form.isConnected === false) return [];
            for (const values of extra.slice(start, start + 256)) rows.push(catalogRecord(values, data, gradeOrder, importanceOrder));
        }
        catalogRecords.set(data, rows);
        return rows;
    })();
    catalogPreparation.set(data, request);
    request.finally(() => catalogPreparation.delete(data)).catch(() => {});
    return request;
}

/** Reuse prepared light records; direct callers can still read small inline catalogs. */
export function catalogRows() {
    const form = document.querySelector("[data-quality-matrix]");
    const data = form && qualityMetadata(form);
    if (!data) return [];
    if (catalogRecords.has(data)) return catalogRecords.get(data);
    const gradeOrder = new Map(data.grades.map((item, index) => [item.value, item.order ?? index]));
    const importanceOrder = new Map(data.importance.map((item, index) => [item.value, item.order ?? index]));
    return (data.extra || []).map(values => catalogRecord(values, data, gradeOrder, importanceOrder));
}

/** Convert only the returned page into renderable article records. */
export function directoryRows(data, rows) {
    const grades = new Map(data.grades.map(({value, order}, index) => [value, order ?? index]));
    const importance = new Map(data.importance.map(({value, order}, index) => [value, order ?? index]));
    return rows.map(values => {
        const row = catalogRecord(values, data, grades, importance);
        row.dataset.cohort = "1";
        return row;
    });
}

/** Build a fresh visible row with the same markup as the prepared article table. */
export function articleElement(record) {
    if (!record.article) return record.cloneNode(true);
    const article = record.article, metadata = record.metadata, row = node("tr");
    const labels = metadata.labels;
    const parenthesis = [labels.parenthesis_open || " (", labels.parenthesis_close || ")"];
    row.setAttribute("data-analysis-row", ""); Object.assign(row.dataset, record.dataset);
    const wikiLink = (title, label) => {const link = node("a", label); link.href = `https://zh.wikipedia.org/wiki/${encodeURIComponent(title.replaceAll(" ", "_"))}`; return link;};
    for (const cell of record.cells) {const item = node("td", cell.textContent); Object.assign(item.dataset, cell.dataset); row.append(item);}
    const talk = node("span", undefined, "analysis-talk");
    talk.append(document.createTextNode(parenthesis[0]), wikiLink(`Talk:${article.title}`, labels.talk || "talk"), document.createTextNode(parenthesis[1]));
    row.cells[1].replaceChildren(wikiLink(article.title, article.title_label), document.createTextNode(" "), talk);
    for (const [column, options, value] of [[2, metadata.grades, article.grade], [3, metadata.importance, article.importance]]) {
        const assessment = options.find(item => item.value === value);
        const label = node("span", undefined, "analysis-assessment-label");
        const icon = svgNode("svg", {viewBox: "0 0 12 12", width: 12, height: 12, class: "analysis-swatch", "aria-hidden": "true"});
        icon.append(svgNode("rect", {width: 12, height: 12, fill: assessment?.article_color || assessment?.color || "#72989c"}));
        label.append(icon, document.createTextNode(assessment?.article_label || assessment?.label || value));
        row.cells[column].replaceChildren(label);
    }
    row.cells[4].replaceChildren();
    if (article.listed_date) {
        const time = node("time", article.date_label);
        time.dateTime = article.listed_date;
        if (article.listed_oldid) {
            const link = node("a");
            link.href = `https://zh.wikipedia.org/w/index.php?oldid=${article.listed_oldid}`;
            link.title = labels.listing_evidence || "";
            link.append(time);
            row.cells[4].append(link);
        } else row.cells[4].append(time);
    } else row.cells[4].append(node("span", labels.unknown_listing, "context"));
    if (article.review_url) {
        const review = node("span", undefined, "analysis-review"), link = node("a", labels.review || "review");
        link.href = article.review_url;
        review.append(document.createTextNode(parenthesis[0]), link, document.createTextNode(parenthesis[1]));
        row.cells[4].append(document.createTextNode(" "), review);
    }
    renderMainContributors(row.cells[5], article, labels);
    if (article.authorship?.available === true) {
        const popupId = `quality-article-${article.page_id}-authorship`;
        const details = node("a", undefined, "analysis-authorship-info");
        details.href = `#${popupId}`; details.title = metadata.labels.authorship_details.replace("{title}", article.title_label);
        details.setAttribute("aria-label", details.title); details.setAttribute("aria-haspopup", "dialog"); details.setAttribute("aria-controls", popupId);
        const icon = svgNode("svg", {width:16,height:16,viewBox:"0 0 20 20","aria-hidden":"true",focusable:"false"});
        icon.append(svgNode("use", {href: metadata.authorshipIcon})); details.append(icon);
        details.addEventListener("click", event => {
            if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault(); event.stopPropagation();
            let dialog = document.querySelector("[data-catalog-authorship]");
            if (!dialog) {dialog = node("dialog", undefined, "ui-dialog page-updates analysis-authorship-dialog"); dialog.setAttribute("data-catalog-authorship", ""); document.body.append(dialog);}
            dialog.id = popupId; dialog.setAttribute("aria-labelledby", `${popupId}-heading`);
            const header = node("header", undefined, "ui-dialog__header"), heading = node("h3", details.getAttribute("aria-label"), "ui-dialog__header__title"), close = node("button", "×", "ui-button ui-dialog__header__close-button"), body = node("div", undefined, "ui-dialog__body");
            heading.id = `${popupId}-heading`; close.type = "button"; close.addEventListener("click", () => dialog.close()); header.append(heading, close); body.append(node("p", metadata.labels.authorship_note));
            renderAuthorshipDetails(body, article.authorship, metadata.labels);
            dialog.replaceChildren(header, body); details.focus(); dialog.showModal();
        });
        row.cells[5].append(document.createTextNode(" "), details);
    }
    row.cells[6].textContent = article.prose_characters === null ? "—" : Math.round(article.prose_characters).toLocaleString("en-US");
    row.cells[7].textContent = article.source_bytes === null ? "—" : (article.source_bytes / 1000).toLocaleString("en-US", {minimumFractionDigits: 1, maximumFractionDigits: 1});
    for (const column of [0, 6, 7]) row.cells[column].classList.add("analysis-number");
    if (article.prose_characters !== null) {if (document.documentElement.lang === "en") row.cells[6].append(document.createTextNode(" ")); row.cells[6].append(node("small", metadata.labels.words));}
    if (article.source_bytes !== null) row.cells[7].append(document.createTextNode(" "), node("small", "kB"));
    return row;
}

/** Show qualified main contributors without turning missing evidence into none. */
export function renderMainContributors(cell, article, labels) {
    cell.replaceChildren();
    if (article.authorship?.available !== true) {
        cell.append(node("span", labels.main_unavailable, "context"));
        return;
    }
    const contributors = article.main_contributors || [];
    if (!contributors.length) {
        cell.append(node("span", labels.no_main_contributors, "context"));
        return;
    }
    for (const contributor of contributors) {
        if (cell.childNodes.length) cell.append(document.createTextNode("、"));
        if (contributor.url) {
            const link = node("a", contributor.label);
            link.href = contributor.url;
            cell.append(link);
        } else cell.append(node("span", contributor.label));
    }
}

/** Distinguish unavailable evidence from a saved result with no qualifying editor. */
export function renderAuthorshipDetails(body, proof, labels) {
    if (proof?.available !== true) {
        body.append(node("p", labels.authorship_unavailable, "notice"));
        return;
    }
    const boundary = node("p");
    if (proof.range_end?.url) {
        const date = node("a", proof.range_end.date || "—");
        date.href = proof.range_end.url;
        boundary.append(document.createTextNode(labels.until), date);
    }
    if (proof.visualization_url) {
        const visual = node("a", labels.visualization);
        visual.href = proof.visualization_url;
        if (boundary.childNodes.length) boundary.append(document.createTextNode(" · "));
        boundary.append(visual);
    }
    if (boundary.childNodes.length) body.append(boundary);
    const table = node("table", undefined, "analysis-editor-table");
    const head = node("thead"), headRow = node("tr"), tbody = node("tbody");
    for (const [label, hint] of [
        [labels.contributors], [labels.editor_share],
        [labels.editor_characters, labels.editor_characters_hint],
        [labels.editor_bytes, labels.editor_bytes_hint],
    ]) {
        const heading = node("th", label);
        if (hint) heading.title = hint;
        headRow.append(heading);
    }
    head.append(headRow);
    for (const editor of proof.editors) {
        const line = node("tr"), name = node("th");
        if (editor.url) {
            const link = node("a", editor.name);
            link.href = editor.url;
            name.append(link);
        } else name.textContent = editor.name;
        line.append(name, node("td", editor.share_label), node("td", editor.characters_label), node("td", editor.bytes_label));
        tbody.append(line);
    }
    if (!proof.editors.length) {
        const row = node("tr"), message = node("td", labels.no_top_editors);
        message.colSpan = 4;
        row.append(message);
        tbody.append(row);
    }
    table.append(head, tbody);
    body.append(table);
}

/** Synchronize matrix checkboxes while leaving the applied cohort in place. */
export function initializeQualitySelection(form) {
    if (!form || form.hasAttribute("data-selection-enhanced")) return;
    form.setAttribute("data-selection-enhanced", "");
    const cells = [...form.querySelectorAll("[data-matrix-cell]")];
    const parents = [
        [form.querySelector("[data-matrix-all]"), cells],
        ...[...form.querySelectorAll("[data-matrix-group]")].map(input => [
            input, cells.filter(cell => cell.dataset.gradeGroup === input.dataset.matrixGroup),
        ]),
        ...[...form.querySelectorAll("[data-matrix-grade]")].map(input => [
            input, cells.filter(cell => cell.dataset.grade === input.dataset.matrixGrade),
        ]),
        ...[...form.querySelectorAll("[data-matrix-importance]")].map(input => [
            input, cells.filter(cell => cell.dataset.importance === input.dataset.matrixImportance),
        ]),
    ].filter(([input]) => input);
    const sync = () => {
        for (const [input, children] of parents) {
            const checked = children.filter(child => child.checked).length;
            input.checked = children.length > 0 && checked === children.length;
            input.indeterminate = checked > 0 && checked < children.length;
        }
    };
    const status = form.querySelector("[data-matrix-status]");
    const message = form.querySelector("[data-matrix-message]");
    const edited = () => {
        form.dataset.qualitySelectionChanged = "1";
        if (message && !form.dataset.qualityChartsLoading) message.textContent = status.dataset.pending;
    };
    for (const [input, children] of parents) input.addEventListener("change", () => {
        for (const child of children) child.checked = input.checked;
        sync();
        edited();
    });
    for (const input of cells) input.addEventListener("change", () => {sync(); edited();});
    for (const input of form.querySelectorAll("[data-matrix-from], [data-matrix-to], [data-matrix-unknown]")) {
        input.addEventListener("input", edited);
        input.addEventListener("change", edited);
    }
    form.addEventListener("submit", event => event.preventDefault());
    sync();
}

/** Use one confirmed selection for every saved summary, figure and directory. */
export function initializeQualityMatrix() {
    const form = document.querySelector("[data-quality-matrix]");
    if (!form || form.hasAttribute("data-matrix-enhanced")) return;
    initializeQualitySelection(form);
    const data = qualityMetadata(form);
    const apply = form.querySelector("[data-matrix-apply]");
    if (!data || !apply) return;
    const remote = Boolean(form.dataset.directoryUrl);
    const inputs = [...form.querySelectorAll("[data-matrix-cell]")];
    const rows = document.querySelector("[data-quality-analysis]")?.analysisRows || [...document.querySelectorAll("[data-analysis-row]")];
    const from = form.querySelector("[data-matrix-from]");
    const to = form.querySelector("[data-matrix-to]");
    const unknown = form.querySelector("[data-matrix-unknown]");
    const status = form.querySelector("[data-matrix-status]");
    const message = status.querySelector("[data-matrix-message]");
    const spinner = status.querySelector("[data-matrix-spinner]");
    const results = document.querySelector("[data-quality-results]");
    const grades = data.grades;
    const key = (grade, level) => grade + ":" + level;
    const yearTable = document.querySelector(".analysis-year-data");
    const yearHead = yearTable?.tHead.rows[0];
    const yearLabel = yearHead?.cells[0].textContent;
    const totalLabel = yearHead?.cells[yearHead.cells.length - 1].textContent;
    const yearHost = document.querySelector('[data-quality-chart="years"]');
    const gradeHost = document.querySelector('[data-quality-chart="grades"]');
    const importanceHost = document.querySelector('[data-quality-chart="importance"]');
    const maximum = data.length_scale_maximum ?? proseLengthMaximum(data.cells);
    const authorRows = [...document.querySelectorAll("[data-matrix-author]")].map(row => {
        const link = row.cells[2].querySelector("a");
        return {
            row, link,
            label: link.textContent.replace(/[\d,]+/, "{count}"),
            pages: row.dataset.pageIds ? JSON.parse(row.dataset.pageIds).map(String) : null,
        };
    });

    function renderDistribution(host, group, options, selected, total, lengths) {
        if (!host) return;
        const groups = new Map();
        for (const cell of selected) {
            const code = cell[group];
            if (!groups.has(code)) groups.set(code, []);
            groups.get(code).push(cell);
        }
        const entries = [];
        for (const option of options) {
            const cells = groups.get(option.value);
            if (!cells) continue;
            const summary = lengths ? {
                pages: cells.reduce((sum, cell) => sum + cell.pages, 0),
                measured: cells.reduce((sum, cell) => sum + cell.measured, 0),
                minimum: null, maximum: null, mean: null,
                quartiles: [null, null], quantiles: [null, null, null], density: [],
                ...lengths[option.value],
            } : combineCells(cells);
            entries.push({option, summary});
        }
        const body = host.closest("figure").querySelector("tbody");
        const tableRows = entries.map(({option, summary}) => {
            const row = node("tr"), heading = node("th");
            heading.scope = "row";
            const caption = node("span", undefined, "analysis-assessment-label");
            caption.append(swatch(option.color), chartLink(group, option.value, option.label));
            heading.append(caption);
            const count = node("span", undefined, "analysis-count");
            count.append(node("span", format(summary.pages)), node("small", (summary.pages / total * 100).toFixed(1) + "%"));
            const countCell = node("td", undefined, "analysis-number");
            countCell.append(count);
            const length = node("td", undefined, "analysis-mini-cell");
            length.dataset.qualityLength = key(group, option.value);
            length.append(violinFigure(summary, group, option, data.labels, maximum));
            row.append(heading, countCell, length);
            return row;
        });
        body.replaceChildren(...tableRows);
        host.replaceChildren(pieFigure(entries, group, total, chartCaption(host)));
    }

    function swatch(color) {
        const svg = svgNode("svg", {viewBox: "0 0 12 12", width: 12, height: 12, class: "analysis-swatch", "aria-hidden": "true"});
        svg.append(svgNode("rect", {width: 12, height: 12, fill: color}));
        return svg;
    }

    function chartCaption(host) {
        return host.dataset.chartCaption || host.querySelector("svg")?.getAttribute("aria-label") || "";
    }

    function renderYears(selected, selectedGrades, firstYear, lastYear) {
        if (!yearTable || !yearHost) return;
        const {years, legend} = qualityYearSummary(selected, selectedGrades, firstYear, lastYear);
        const legendList = document.querySelector(".analysis-legend");
        if (legendList) legendList.replaceChildren(...legend.map(grade => {
            const item = node("li");
            item.append(swatch(grade.color), document.createTextNode(" " + grade.label));
            return item;
        }));
        const head = node("tr");
        for (const label of [yearLabel, ...selectedGrades.map(grade => grade.label), totalLabel]) {
            const column = node("th", label);
            column.scope = "col";
            head.append(column);
        }
        head.lastElementChild.className = "analysis-total-column";
        yearTable.tHead.replaceChildren(head);
        yearTable.tBodies[0].replaceChildren(...years.map(year => {
            const row = node("tr"), label = node("th", year.year);
            label.scope = "row";
            row.append(label, ...year.grades.map(count => node("td", count)));
            row.append(node("td", format(year.pages), "analysis-total-column"));
            return row;
        }));
        yearHost.replaceChildren(annualFigure(years, selectedGrades, chartCaption(yearHost)));
    }

    const distributionGrades = [...grades].sort((left, right) =>
        (left.distribution_order ?? left.order) - (right.distribution_order ?? right.order));
    function render(selection, summary) {
        const selected = summary?.cells ?? data.cells.filter(cell =>
            matchesQualitySelection(selection, cell.grade, cell.importance, cell.year));
        const total = selected.reduce((sum, cell) => sum + cell.pages, 0);
        renderDistribution(gradeHost, "grade", distributionGrades, selected, total, summary?.lengths.grade);
        renderDistribution(importanceHost, "importance", data.importance, selected, total, summary?.lengths.importance);
        renderYears(selected, grades.filter(grade => selection.grades.has(grade.value)), selection.firstYear, selection.lastYear);
        const undated = summary?.undated ?? data.cells.reduce((count, cell) =>
            count + (cell.year === null && selection.chosen.has(key(cell.grade, cell.importance)) ? cell.pages : 0), 0);
        const undatedLabel = document.querySelector("[data-undated-count]");
        if (undatedLabel) undatedLabel.textContent = undatedLabel.dataset.label.replace("{count}", format(undated));

        const ids = new Set();
        form.qualitySelection = selection;
        if (summary) {
            form.qualityCoverage = summary.coverage;
        } else {
            for (const row of rows) {
                const keep = matchesQualitySelection(selection, row.dataset.grade, row.dataset.importance, row.dataset.year);
                row.dataset.cohort = keep ? "1" : "0";
                if (keep) ids.add(row.dataset.pageId);
            }
            form.qualitySelectedIds = ids;
            for (const row of document.querySelectorAll("[data-matrix-page]")) {
                row.dataset.cohort = ids.has(row.dataset.matrixPage) ? "1" : "0";
            }
        }
        for (const {row, link, label, pages} of authorRows) {
            const dialog = pages ? null : document.getElementById(link.getAttribute("aria-controls"));
            const count = summary
                ? (Object.hasOwn(summary.author_counts, row.dataset.matrixAuthor) ? summary.author_counts[row.dataset.matrixAuthor] : 0)
                : (pages ? pages.filter(id => ids.has(id)).length :
                    dialog?.querySelectorAll('[data-matrix-page][data-cohort="1"]').length ?? 0);
            row.dataset.cohort = count ? "1" : "0";
            row.cells[2].dataset.sort = String(count);
            link.textContent = label.replace("{count}", String(count));
        }
        const totalNode = document.querySelector("[data-matrix-total]");
        if (totalNode) totalNode.textContent = format(total);
        document.dispatchEvent(new Event("quality-cohort-change"));
        document.dispatchEvent(new Event("quality-charts-replaced"));
    }

    function selection(checked, firstYear, lastYear, includeUnknown) {
        return {
            firstYear, lastYear, includeUnknown,
            chosen: new Set(checked.map(input => key(input.dataset.grade, input.dataset.importance))),
            grades: new Set(checked.map(input => input.dataset.grade)),
        };
    }

    async function confirm(event) {
        event.preventDefault();
        if (form.dataset.qualityChartsLoading) return;
        if (Number(from.value) > Number(to.value)) {
            message.textContent = status.dataset.yearOrder;
            to.focus();
            return;
        }
        const chosen = selection(inputs.filter(input => input.checked), Number(from.value), Number(to.value), unknown.checked);
        delete form.dataset.qualitySelectionChanged;
        form.dataset.qualityChartsLoading = "1";
        apply.setAttribute("aria-disabled", "true");
        results?.setAttribute("aria-busy", "true");
        spinner.hidden = false;
        message.textContent = status.dataset.working;
        try {
            // Paint the progress state before combining the saved cells.
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            if (!form.isConnected) return;
            const summary = remote ? await requestQualityPage(form, chosen, {view: "summary"}) : null;
            if (!form.isConnected) return;
            render(chosen, summary);
            message.textContent = form.dataset.qualitySelectionChanged ? status.dataset.pending : status.dataset.applied;
        } catch {
            message.textContent = status.dataset.failed;
        } finally {
            delete form.dataset.qualityChartsLoading;
            apply.removeAttribute("aria-disabled");
            results?.removeAttribute("aria-busy");
            spinner.hidden = true;
        }
    }

    const defaultGrades = new Set(grades.filter(grade => grade.checked).map(grade => grade.value));
    const defaults = selection(inputs.filter(input => defaultGrades.has(input.dataset.grade)), Number(from.min), Number(to.max), true);
    if (remote) form.qualitySelection = defaults;
    else render(defaults);
    form.setAttribute("data-matrix-enhanced", "");
    form.addEventListener("submit", event => void confirm(event));
    apply.hidden = false;
    apply.disabled = false;
}
