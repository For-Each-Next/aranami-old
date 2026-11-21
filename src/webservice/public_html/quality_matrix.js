/** Combine saved matrix statistics and keep every report view in one cohort. */
import { groupedNumber } from "./number_format.js";

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

/** Sum observed contribution counts for the selected articles. */
export function selectedAuthorTotals(contributions, ids) {
    let prose = null, bytes = null;
    for (const [id, characters, size] of contributions) {
        if (!ids.has(String(id))) continue;
        if (characters !== null) prose = (prose ?? 0) + characters;
        if (size !== null) bytes = (bytes ?? 0) + size;
    }
    return {prose, bytes};
}

function measurementUnit(label) {
    const unit = label.trim();
    const small = node("small", " " + unit, "analysis-unit");
    small.dataset.unit = unit;
    return small;
}

function displayProse(cell, count, unit) {
    cell.textContent = count == null ? "—" : groupedNumber(count / 1000, true);
    if (count != null) cell.append(measurementUnit(unit));
}

function renderAuthorTotals(row, {prose, bytes}, words) {
    const proseCell = row.querySelector("[data-contributed-prose]");
    const sizeCell = row.querySelector("[data-contributed-bytes]");
    if (!proseCell || !sizeCell) return;
    proseCell.dataset.sort = prose ?? "";
    displayProse(proseCell, prose, words);
    sizeCell.dataset.sort = bytes ?? "";
    sizeCell.textContent = bytes === null ? "—" : groupedNumber(bytes / 1000, true);
    if (bytes !== null) sizeCell.append(measurementUnit("kB"));
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

/** Sample the selected cohort with Scott's bandwidth and peak normalization. */
function violinDensity(histogram, minimum, maximum, count, mean) {
    if (minimum === maximum) return [];
    const variance = histogram.reduce((sum, [value, frequency]) => sum + frequency * (value - mean) ** 2, 0) / (count - 1);
    const bandwidth = Math.sqrt(variance) * count ** -.2;
    const samplePoints = 100;
    const points = Array.from({length: samplePoints}, (_, index) => {
        const position = minimum + (maximum - minimum) * (index / (samplePoints - 1));
        const density = histogram.reduce((sum, [value, frequency]) =>
            sum + frequency * Math.exp(-.5 * ((value - position) / bandwidth) ** 2), 0);
        return [position, density];
    });
    const peak = Math.max(...points.map(([, density]) => density));
    return points.map(([position, density]) => [position, density / peak]);
}

/** Add prepared cells, retaining missing length measurements separately. */
export function combineCells(cells) {
    const histogram = new Map();
    let pages = 0, measured = 0;
    for (const cell of cells) {
        pages += cell.pages;
        measured += cell.measured;
        for (const item of cell.histogram) histogram.set(item.value, (histogram.get(item.value) || 0) + item.count);
    }
    const observed = [...histogram].filter(([, count]) => count > 0);
    const lengths = observed.map(([value]) => value);
    const count = observed.reduce((sum, [, frequency]) => sum + frequency, 0);
    const mean = count ? observed.reduce((sum, [value, frequency]) => sum + value * frequency, 0) / count : null;
    const minimum = count ? Math.min(...lengths) : null;
    const maximum = count ? Math.max(...lengths) : null;
    return {
        pages, measured, mean, minimum, maximum,
        quantiles: [.025, .16, .5, .84, .975].map(p => histogramQuantile(histogram, p)),
        quartiles: [.25, .75].map(p => histogramQuantile(histogram, p)),
        density: violinDensity(observed, minimum, maximum, count, mean),
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

/** Keep the 25,000-character linear body and the compressed tail. */
export function proseLengthPosition(characters, maximum) {
    if (characters <= 25000) return Math.max(0, characters / 25000 * 900);
    if (maximum <= 25000) return 900;
    return Math.min(1000, 900 + 100 * Math.log(characters / 25000) / Math.log(maximum / 25000));
}

/** Read a prose measurement from the shared linear and logarithmic axis. */
export function proseLengthAt(position, maximum) {
    if (position <= 900 || maximum <= 25000)
        return Math.max(0, Math.min(900, position)) / 900 * 25000;
    return 25000 * (maximum / 25000) ** ((Math.min(1000, position) - 900) / 100);
}

/** Round prose measurements to two significant digits with integer labels. */
function proseLengthLabel(value) {
    if (value === null) return "—";
    const step = value > 0 ? 10 ** Math.max(0, Math.floor(Math.log10(value)) - 1) : 1;
    return groupedNumber(Math.round(value / step) * step);
}

/** Give each percentile mark its own localized native tooltip. */
export function violinMarkerTitle(kind, value, labels) {
    const names = {minimum: "Shortest length", p25: "Lower quartile length", p50: "Median length", p75: "Upper quartile length", maximum: "Longest length", mean: "Average length"};
    const template = labels[`violin_${kind}`] || `${names[kind]} ({value} {unit})`;
    return template.replaceAll("{value}", groupedNumber(value / 1000, true))
        .replaceAll("{unit}", labels.words || "thousand characters");
}

/** Keep article counts exact while rounding length labels for display. */
export function violinSummary(statistics, template, labels = {}) {
    if (statistics.minimum !== null && statistics.minimum === statistics.maximum) {
        const singleTemplate = labels.violin_single || "{value} characters, measured for {measured} of {pages} articles and lists.";
        return singleTemplate.replace("{value}", proseLengthLabel(statistics.minimum))
            .replace("{measured}", groupedNumber(statistics.measured))
            .replace("{pages}", groupedNumber(statistics.pages));
    }
    const values = {
        pages: groupedNumber(statistics.pages), measured: groupedNumber(statistics.measured),
        minimum: proseLengthLabel(statistics.minimum), maximum: proseLengthLabel(statistics.maximum),
        p25: proseLengthLabel(statistics.quartiles[0]), p50: proseLengthLabel(statistics.quantiles[2]), p75: proseLengthLabel(statistics.quartiles[1]),
    };
    if (statistics.measured > 1 && statistics.measured < 4 && labels.violin_range) {
        const range = labels.violin_range.replace(/\{(pages|measured|minimum|maximum)\}/g, (_, key) => values[key]);
        const mean = violinMarkerTitle("mean", statistics.mean, labels);
        const median = statistics.measured === 3 ? ` ${violinMarkerTitle("p50", statistics.quantiles[2], labels)}.` : "";
        return `${range}${median} ${mean}.`;
    }
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
const format = value => value === null ? "—" : groupedNumber(value);

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

/** Interpolate the saved density at an exact observed endpoint. */
function densityAt(points, position) {
    const index = points.findIndex(([value]) => value >= position);
    if (index < 0) return points.at(-1)[1];
    if (index === 0) return points[0][1];
    const [left, low] = points[index - 1], [right, high] = points[index];
    const fraction = (position - left) / (right - left);
    return low + fraction * (high - low);
}

/** Clip to measured bounds and normalize each shape to unit peak height. */
export function violinHeightDensity({density, minimum, maximum}) {
    if (!density.length || minimum == null || maximum <= minimum) return [];
    const support = [
        [minimum, densityAt(density, minimum)],
        ...density.filter(([length]) => length > minimum && length < maximum),
        [maximum, densityAt(density, maximum)],
    ];
    const peak = Math.max(...support.map(([, height]) => height));
    return peak > 0 ? support.map(([value, height]) => [value, height / peak]) : [];
}

/** Give the largest measured group the full height, losing 10% per decade. */
export function violinHeight(measured, maximumMeasured) {
    return measured > 0 ? 1 + Math.log10(measured / maximumMeasured) / 10 : 0;
}

/** Mirror the sampled density as a closed polygon over the observed range. */
export function violinDensityPath(density, maximum, scale = 18) {
    if (density.length < 2) return "";
    const points = density.map(([value, height]) => [(10 + proseLengthPosition(value, maximum)).toFixed(3), scale * height]);
    const top = points.map(([x, height]) => `${x} ${(22 - height).toFixed(3)}`);
    const bottom = points.toReversed().map(([x, height]) => `${x} ${(22 + height).toFixed(3)}`);
    return `M ${top.concat(bottom).join(" L ")} Z`;
}

/** Draw measured lengths and show one bar for a single distinct value. */
function violinFigure(summary, group, option, labels, maximum, maximumMeasured) {
    const description = violinSummary(summary, labels.violin_summary, labels);
    const caption = option.label + " · " + description;
    const svg = svgNode("svg", {
        viewBox: "0 0 1020 44", preserveAspectRatio: "none", role: "group",
        class: "analysis-mini-violin", "aria-label": caption,
        "data-analysis-violin": option.value, "data-chart-renderer": "browser",
        "data-length-start": 10, "data-length-end": 1010,
        "data-length-maximum": maximum, "data-length-unit": labels.words,
    });
    const plot = svgNode("g");
    const x = value => 10 + proseLengthPosition(value, maximum);
    plot.append(svgNode("line", {x1: 10, x2: 1010, y1: 22, y2: 22, class: "analysis-violin-track"}));
    const height = 18 * violinHeight(summary.measured, maximumMeasured);
    const outline = violinDensityPath(summary.density, maximum, height);
    const capHeight = outline ? height / 2 : 7;
    if (outline) {
        plot.append(svgNode("path", {
            d: outline,
            class: "analysis-violin-density", fill: option.color,
        }), svgNode("line", {
            x1: x(summary.minimum), x2: x(summary.maximum), y1: 22, y2: 22, class: "analysis-violin-spine",
        }));
    }
    const markers = summary.minimum !== null && summary.minimum === summary.maximum
        ? {length: summary.minimum}
        : {minimum: summary.minimum,
            ...(summary.measured >= 4 ? {p25: summary.quartiles[0]} : {}),
            ...(summary.measured >= 3 ? {p50: summary.quantiles[2]} : {}),
            ...(summary.measured >= 4 ? {p75: summary.quartiles[1]} : {}),
            maximum: summary.maximum, mean: summary.mean};
    for (const [kind, value] of Object.entries(markers)) {
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
                mark.append(svgNode("line", {x1: position - 8, x2: position + 8, y1: 22 - 3 * direction, y2: 22 + 3 * direction}));
            }
        } else if (kind === "p25" || kind === "p75") {
            mark = svgNode("line", {
                ...attributes, class: "analysis-violin-quartile", "data-percentile": kind.slice(1),
                x1: position, x2: position, y1: 19, y2: 25,
            });
        } else {
            const halfHeight = kind === "p50" ? 5 : capHeight;
            mark = svgNode("line", {
                ...attributes, class: kind === "length" ? "analysis-violin-single"
                    : kind === "p50" ? "analysis-violin-median" : "analysis-violin-extreme",
                x1: position, x2: position, y1: 22 - halfHeight, y2: 22 + halfHeight,
                ...(kind === "minimum" || kind === "maximum" ? {"data-extreme": kind} : {}),
            });
        }
        const title = kind === "length" ? description : violinMarkerTitle(kind, value, labels);
        mark.setAttribute("aria-label", title);
        if (kind !== "length") mark.dataset.markerLabel = title;
        plot.append(mark);
    }
    const link = chartLink(group, option.value, option.label, undefined, true);
    link.setAttribute("aria-label", caption);
    link.dataset.chartMeasured = "1";
    link.append(plot);
    svg.append(link);
    return svg;
}

/** Place ticks at whole numbers on a rounded annual-count scale. */
export function annualCountTicks(maximum) {
    const approximate = Math.max(1, maximum / 5);
    const magnitude = 10 ** Math.floor(Math.log10(approximate));
    const interval = [1, 2, 5, 10].map(step => step * magnitude).find(step => step >= approximate);
    const count = Math.max(1, Math.ceil(maximum / interval));
    return Array.from({length: count + 1}, (_, index) => index * interval);
}

/** Draw summed annual counts and link each stacked bar to its articles. */
function annualFigure(years, grades, caption) {
    const width = Math.max(420, 54 + years.length * 44);
    const svg = svgNode("svg", {
        viewBox: `0 0 ${width} 300`, width, height: 300, class: "analysis-year-columns",
        role: "group", "aria-label": caption, "data-chart-renderer": "browser",
    });
    const base = 260, left = 48, step = (width - left - 6) / years.length;
    const ticks = annualCountTicks(Math.max(0, ...years.map(year => year.pages)));
    const height = count => 216 * count / ticks.at(-1);
    for (const count of ticks) {
        const y = base - height(count);
        svg.append(svgNode("line", {x1: left, x2: width - 6, y1: y, y2: y, class: "analysis-year-grid"}),
            svgNode("text", {x: left - 6, y, "text-anchor": "end", "dominant-baseline": "middle",
                class: "analysis-axis-label analysis-year-count-label"}, count));
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

/** Read exact saved marks and compute the display density. */
function savedViolin(saved) {
    const summary = {
        pages: saved.pages, measured: saved.measured,
        minimum: saved.extrema.find(mark => mark.kind === "minimum")?.value ?? null,
        maximum: saved.extrema.find(mark => mark.kind === "maximum")?.value ?? null,
        mean: saved.mean ?? null, quantiles: [null, null, saved.median_characters ?? null],
        quartiles: [25, 75].map(percentile =>
            saved.quartiles.find(mark => mark.percentile === percentile)?.value ?? null),
        density: (saved.density || []).map(({position, density}) => [position, density]),
    };
    return {...summary, density: violinHeightDensity(summary)};
}

/** Draw the default figures directly from the prepared overview. */
export function initializeQualityFigures(form) {
    if (!form?.qualityOverview) return;
    const {analysis, labels} = form.qualityOverview;
    delete form.qualityOverview;
    const maximum = analysis.length_scale_maximum;
    const summaries = new Map([...analysis.grades, ...analysis.importance_totals]
        .filter(row => row.length)
        .map(row => [row.length, savedViolin(row.length)]));
    const maximumMeasured = Math.max(0, ...Array.from(summaries.values(), summary => summary.measured));
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
            const summary = summaries.get(saved);
            const option = {value, label: saved.label, color: saved.color};
            cell.replaceChildren(violinFigure(summary, group, option, labels, maximum, maximumMeasured));
        }
    }
    const host = document.querySelector('[data-quality-chart="years"]');
    if (!host) return;
    const grades = analysis.year_chart_grades;
    const years = analysis.years.map(({year, pages, grades: counts}) => ({
        year, pages, grades: grades.map(grade => counts[grade.value] ?? 0),
    }));
    host.replaceChildren(annualFigure(years, grades, host.dataset.chartCaption));
}

const catalogRecords = new WeakMap();
const catalogPreparation = new WeakMap();
const catalogFields = ["page_id", "title", "grade", "importance", "listed_date", "listed_oldid", "prose_characters", "source_bytes", "authors", "title_label", "date_label", "authorship", "review_url", "main_contributors", "details"];

/** Read one saved article without constructing a directory row. */
export function catalogArticle(values) {
    return Object.fromEntries(catalogFields.map((key, index) => [key, values[index]]));
}

/** Build one light sortable record without creating table elements. */
function catalogRecord(values, data, gradeOrder, importanceOrder) {
    const article = catalogArticle(values);
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
export function articleElement(record, includeContributors = false) {
    if (!record.article) {
        const copy = record.cloneNode(true);
        if (includeContributors) attachInlineChartDetail(copy);
        return copy;
    }
    const article = record.article, metadata = record.metadata, row = node("tr");
    const labels = metadata.labels;
    row.setAttribute("data-analysis-row", ""); Object.assign(row.dataset, record.dataset);
    for (const cell of record.cells) {const item = node("td", cell.textContent); Object.assign(item.dataset, cell.dataset); row.append(item);}
    row.cells[1].replaceChildren(articleLink(article));
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
        if (article.review_url) {
            const link = node("a");
            link.href = article.review_url;
            link.title = labels.review || "";
            link.append(time);
            row.cells[4].append(link);
        } else row.cells[4].append(time);
    } else row.cells[4].append(node("span", labels.unknown_listing, "context"));
    renderMainContributors(row.cells[5], article, labels);
    row.cells[1].append(document.createTextNode(" "), articleDetailLink(article, metadata, {includeContributors}));
    if (!includeContributors && article.authorship?.available)
        row.cells[5].append(document.createTextNode(" "), articleDetailLink(article, metadata, {more: true}));
    displayProse(row.cells[6], article.prose_characters, labels.words);
    row.cells[7].textContent = article.source_bytes === null ? "—" : groupedNumber(article.source_bytes / 1000, true);
    for (const column of [0, 6, 7]) row.cells[column].classList.add("analysis-number");
    if (article.source_bytes !== null) row.cells[7].append(measurementUnit("kB"));
    return row;
}

function articleLink(article) {
    const link = node("a", article.title_label);
    link.href = `https://zh.wikipedia.org/wiki/${encodeURIComponent(article.title.replaceAll(" ", "_"))}`;
    return link;
}

/** Open article metadata, contributor evidence, or a saved grade comparison. */
export function articleDetailLink(article, metadata, {more = false, includeContributors = false, comparison} = {}) {
    const labels = metadata.labels;
    const suffix = more ? "authorship" : comparison ? "comparison-details" : includeContributors ? "chart-details" : "details";
    const popupId = `quality-article-${article.page_id}-${suffix}`;
    const details = node("a", undefined, "analysis-authorship-info");
    const title = (more ? labels.authorship_details : labels.article_details) || "{title}";
    details.href = `#${popupId}`;
    details.title = title.replace("{title}", article.title_label);
    details.setAttribute("aria-label", details.title);
    details.setAttribute("aria-haspopup", "dialog");
    details.setAttribute("aria-controls", popupId);
    const source = metadata.authorshipIcon || "/assets/icons/report-icons.svg#message-notice";
    const icon = svgNode("svg", {width: 16, height: 16, viewBox: "0 0 20 20", "aria-hidden": "true", focusable: "false"});
    if (more) icon.setAttribute("class", "analysis-more-authors");
    icon.append(svgNode("use", {href: more ? source.split("#", 1)[0] + "#circle-plus" : source}));
    details.append(icon);
    bindArticleDialog(details, more, labels.close, body => {
        if (!more) renderArticleDetails(body, article, labels);
        if (comparison) {
            const fields = node("dl", undefined, "analysis-detail-fields analysis-source-comparison");
            for (const [label, content] of comparison) detailField(fields, label, content);
            body.append(fields);
        }
        if (more || includeContributors) {
            const proof = more ? body : contributorSection(body, labels.significant_contributors);
            proof.append(node("p", labels.authorship_note));
            renderAuthorshipDetails(proof, article.authorship, labels);
        }
    });
    return details;
}

function contributorSection(body, title) {
    const section = node("section", undefined, "analysis-article-contributors");
    section.append(node("h4", title));
    body.append(section);
    return section;
}

/** Give chart rows their own combined details even with an inline catalog. */
function attachInlineChartDetail(row) {
    const link = row.cells[1].querySelector?.("a[aria-controls]");
    const id = link?.getAttribute("aria-controls");
    const source = id && document.getElementById(id);
    if (!source?.matches(".analysis-article-dialog")) return;
    const grid = source.querySelector(".analysis-detail-grid");
    const proof = document.getElementById(id.replace(/-details$/, "-authorship"));
    const chartId = id.replace(/-details$/, "-chart-details");
    link.href = `#${chartId}`;
    link.setAttribute("aria-controls", chartId);
    bindArticleDialog(link, false, source.querySelector("button").getAttribute("aria-label"), body => {
        body.append(grid.cloneNode(true));
        const section = contributorSection(body, grid.dataset.significantLabel);
        if (proof) {
            for (const child of proof.querySelector(".ui-dialog__body").children) section.append(child.cloneNode(true));
        } else {
            section.append(node("p", grid.dataset.authorshipUnavailable, "notice"));
        }
    });
}

function bindArticleDialog(link, authorshipOnly, closeLabel, render) {
    link.addEventListener("click", event => {
        if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const id = link.getAttribute("aria-controls");
        if (document.getElementById(id)?.matches("dialog:not([data-catalog-authorship])")) return;
        event.preventDefault();
        event.stopPropagation();
        let dialog = document.querySelector("[data-catalog-authorship]");
        if (!dialog) {
            dialog = node("dialog");
            dialog.setAttribute("data-catalog-authorship", "");
            document.body.append(dialog);
        }
        const kind = authorshipOnly ? "analysis-authorship-dialog" : "analysis-article-dialog";
        dialog.className = `ui-dialog page-updates ${kind}`;
        dialog.id = id;
        dialog.setAttribute("aria-labelledby", `${id}-heading`);
        const header = node("header", undefined, "ui-dialog__header");
        const heading = node("h3", link.title, "ui-dialog__header__title");
        heading.id = `${id}-heading`;
        const close = node("button", "×", "ui-button ui-dialog__header__close-button");
        close.type = "button";
        close.setAttribute("aria-label", closeLabel || "Close");
        close.addEventListener("click", () => dialog.close());
        header.append(heading, close);
        const body = node("div", undefined, "ui-dialog__body");
        render(body);
        dialog.replaceChildren(header, body);
        link.focus();
        dialog.showModal();
    });
}

function detailTime(stamp, unknown) {
    const time = stamp ? node("time", stamp.label) : node("span", unknown);
    if (stamp) time.dateTime = stamp.value;
    return time;
}

function detailField(fields, label, content) {
    const value = node("dd");
    value.append(content);
    fields.append(node("dt", label), value);
}

function renderArticleDetails(body, article, labels) {
    const details = article.details || article;
    const unknown = details.unknown || labels.unknown || "—";
    const grid = node("div", undefined, "analysis-detail-grid");
    const fields = node("dl", undefined, "analysis-detail-fields");
    detailField(fields, labels.article, articleLink(article));
    detailField(fields, labels.created, detailTime(details.created, unknown));
    detailField(fields, labels.last_edited, detailTime(details.latest, unknown));
    const prose = node("span");
    displayProse(prose, details.prose_characters, labels.words);
    detailField(fields, labels.prose, prose);
    const size = node("span", details.source_bytes == null ? "—" : groupedNumber(details.source_bytes / 1000, true));
    if (details.source_bytes != null) size.append(measurementUnit("kB"));
    detailField(fields, labels.source_size, size);
    const column = node("div");
    const context = node("dl", undefined, "analysis-detail-fields");
    detailField(context, labels.peak_edit_year, String(details.activity?.peak_year ?? unknown));
    column.append(context);
    if (details.activity) column.append(editActivity(details.activity, labels.edit_history));
    grid.append(fields, column);
    body.append(grid);
}

function editActivity(chart, label) {
    const activity = node("div", undefined, "analysis-activity");
    const svg = svgNode("svg", {viewBox: chart.viewbox, role: "img", "aria-label": `${label} · ${chart.peak_label}`});
    const peak = svgNode("circle", {cx: chart.peak_x, cy: chart.peak_y, r: 3});
    peak.append(svgNode("title", {}, chart.peak_label));
    svg.append(svgNode("path", {d: "M 4 44 H 212"}), svgNode("polyline", {points: chart.points}), peak);
    const years = node("div", undefined, "analysis-activity-years");
    years.append(node("span", chart.first));
    if (chart.first !== chart.last) years.append(node("span", chart.last));
    activity.append(svg, years);
    return activity;
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
            const link = node("a", contributor.article_label || contributor.label);
            link.href = contributor.url;
            if (contributor.article_label) link.title = contributor.label;
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
    table.setAttribute("data-no-pagination", "");
    const head = node("thead"), headRow = node("tr"), tbody = node("tbody");
    for (const [label, hint] of [
        ["#"], [labels.significant_contributors || "Significant contributors"],
        [labels.editor_characters, labels.editor_characters_hint],
        [labels.editor_bytes, labels.editor_bytes_hint],
        [labels.editor_share],
    ]) {
        const heading = node("th", label);
        heading.scope = "col";
        if (hint) heading.title = hint;
        headRow.append(heading);
    }
    head.append(headRow);
    function editorRow(editor, index) {
        const line = node("tr"), name = node("th");
        name.scope = "row";
        if (editor.total) {
            line.className = "analysis-editor-total";
            name.append(node("strong", editor.label));
        } else if (editor.url) {
            const link = node("a", editor.name);
            link.href = editor.url;
            name.append(link);
        } else name.textContent = editor.name || editor.label;
        const source = node("td", editor.bytes_label, "analysis-number");
        if (editor.raw_bytes != null) source.append(measurementUnit("kB"));
        if (editor.bytes_title) source.title = editor.bytes_title;
        const prose = node("td", undefined, "analysis-number");
        displayProse(prose, editor.prose_characters, labels.words);
        line.append(node("td", index, "analysis-number"), name, prose, source,
            node("td", editor.share_label, "analysis-number"));
        return line;
    }
    proof.editors.forEach((editor, index) => tbody.append(editorRow(editor, index + 1)));
    if (!proof.editors.length) {
        const row = node("tr"), message = node("td", labels.no_top_editors);
        message.colSpan = 5;
        row.append(message);
        tbody.append(row);
    }
    for (const editor of proof.summary_rows || []) tbody.append(editorRow(editor, editor.index));
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
    const yearHost = document.querySelector('[data-quality-chart="years"]');
    const gradeHost = document.querySelector('[data-quality-chart="grades"]');
    const importanceHost = document.querySelector('[data-quality-chart="importance"]');
    const maximum = data.length_scale_maximum ?? proseLengthMaximum(data.cells);
    const authorRows = [...document.querySelectorAll("[data-matrix-author]")].map(row => {
        const link = row.cells[2].querySelector("a");
        return {
            row, link,
            unit: link.querySelector(".analysis-unit")?.dataset.unit || "",
            pages: row.dataset.pageIds ? JSON.parse(row.dataset.pageIds).map(String) : null,
            contributions: row.dataset.authorContributions ? JSON.parse(row.dataset.authorContributions) : [],
        };
    });

    function distributionEntries(group, options, selected, lengths) {
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
            entries.push({option, summary: {...summary, density: violinHeightDensity(summary)}});
        }
        return entries;
    }

    function renderDistribution(host, group, entries, total, maximumMeasured) {
        if (!host) return;
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
            length.append(violinFigure(summary, group, option, data.labels, maximum, maximumMeasured));
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
        if (!yearHost) return;
        const {years, legend} = qualityYearSummary(selected, selectedGrades, firstYear, lastYear);
        const legendList = document.querySelector(".analysis-legend");
        if (legendList) legendList.replaceChildren(...legend.map(grade => {
            const item = node("li");
            item.append(swatch(grade.color), document.createTextNode(" " + grade.label));
            return item;
        }));
        yearHost.replaceChildren(annualFigure(years, selectedGrades, chartCaption(yearHost)));
    }

    const distributionGrades = [...grades].sort((left, right) =>
        (left.distribution_order ?? left.order) - (right.distribution_order ?? right.order));
    function render(selection, summary) {
        const selected = summary?.cells ?? data.cells.filter(cell =>
            matchesQualitySelection(selection, cell.grade, cell.importance, cell.year));
        const total = selected.reduce((sum, cell) => sum + cell.pages, 0);
        const gradeEntries = distributionEntries("grade", distributionGrades, selected, summary?.lengths.grade);
        const importanceEntries = distributionEntries("importance", data.importance, selected, summary?.lengths.importance);
        const maximumMeasured = Math.max(0, ...[...gradeEntries, ...importanceEntries].map(({summary}) => summary.measured));
        renderDistribution(gradeHost, "grade", gradeEntries, total, maximumMeasured);
        renderDistribution(importanceHost, "importance", importanceEntries, total, maximumMeasured);
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
        for (const {row, link, unit, pages, contributions} of authorRows) {
            const dialog = pages ? null : document.getElementById(link.getAttribute("aria-controls"));
            const name = row.dataset.matrixAuthor;
            const count = summary
                ? (Object.hasOwn(summary.author_counts, name) ? summary.author_counts[name] : 0)
                : (pages ? pages.filter(id => ids.has(id)).length :
                    dialog?.querySelectorAll('[data-matrix-page][data-cohort="1"]').length ?? 0);
            row.dataset.cohort = count ? "1" : "0";
            row.cells[2].dataset.sort = String(count);
            const countUnit = data.labels[count === 1 ? "article_count_unit_one" : "article_count_unit"] ?? unit;
            link.replaceChildren(document.createTextNode(groupedNumber(count)), measurementUnit(countUnit));
            const totals = summary
                ? (Object.hasOwn(summary.author_totals || {}, name) ? summary.author_totals[name] : null)
                : selectedAuthorTotals(contributions, ids);
            if (totals) renderAuthorTotals(row, totals, data.labels.words);
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
