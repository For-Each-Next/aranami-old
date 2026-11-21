/** Keep keyboard navigation on saved and browser-rendered SVG figures. */
import { groupedNumber } from "./number_format.js";
import { proseLengthAt, proseLengthPosition } from "./quality_matrix.js";

const figures = new WeakMap();
const violinGuides = new WeakSet();
let lengthLabel;

function addLengthGuide(svg) {
    if (violinGuides.has(svg)) return;
    const start = Number(svg.dataset.lengthStart), end = Number(svg.dataset.lengthEnd);
    const maximum = Number(svg.dataset.lengthMaximum);
    if (end <= start || !maximum) return;
    violinGuides.add(svg);
    const guide = document.createElementNS("http://www.w3.org/2000/svg", "line");
    guide.setAttribute("class", "analysis-violin-guide");
    guide.setAttribute("aria-hidden", "true");
    svg.addEventListener("pointermove", event => {
        if (event.pointerType === "touch") return;
        const bounds = svg.getBoundingClientRect();
        const view = svg.viewBox.baseVal;
        if (!bounds.width) return;
        const cursor = view.x + (event.clientX - bounds.left) / bounds.width * view.width;
        const position = Math.max(0, Math.min(1000, 1000 * (cursor - start) / (end - start)));
        const marker = event.target.closest("[data-statistic]")?.dataset.value;
        const length = marker === undefined ? proseLengthAt(position, maximum) : Number(marker);
        const x = marker === undefined ? start + position / 1000 * (end - start)
            : start + proseLengthPosition(length, maximum) / 1000 * (end - start);
        guide.setAttribute("x1", x);
        guide.setAttribute("x2", x);
        guide.setAttribute("y1", view.y);
        guide.setAttribute("y2", view.y + view.height);
        if (!guide.isConnected) svg.append(guide);
        if (!lengthLabel) {
            lengthLabel = document.createElement("span");
            lengthLabel.className = "analysis-violin-length-label";
            lengthLabel.setAttribute("aria-hidden", "true");
            document.body.append(lengthLabel);
        }
        lengthLabel.textContent = groupedNumber(length / 1000, true);
        lengthLabel.dataset.unit = svg.dataset.lengthUnit;
        lengthLabel.hidden = false;
        const markerX = bounds.left + (x - view.x) / view.width * bounds.width;
        lengthLabel.style.left = Math.max(4, Math.min(markerX + 6, innerWidth - lengthLabel.offsetWidth - 4)) + "px";
        lengthLabel.style.top = Math.max(4, bounds.top - lengthLabel.offsetHeight - 2) + "px";
    });
    svg.addEventListener("pointerleave", () => {
        guide.remove();
        if (lengthLabel) lengthLabel.hidden = true;
    });
}

/** Keep the visible rectangle inside the original figure at a bounded scale. */
function constrain(state) {
    const [x, y, width, height] = state.original;
    state.view[2] = Math.max(width / 16, Math.min(width, state.view[2]));
    state.view[3] = height * state.view[2] / width;
    state.view[0] = Math.max(x, Math.min(x + width - state.view[2], state.view[0]));
    state.view[1] = Math.max(y, Math.min(y + height - state.view[3], state.view[1]));
    state.svg.setAttribute("viewBox", state.view.join(" "));
}

/** Zoom around the current center, preserving the figure's aspect ratio. */
function zoom(state, factor) {
    const width = state.view[2], height = state.view[3];
    state.view[2] *= factor;
    state.view[3] *= factor;
    state.view[0] += (width - state.view[2]) / 2;
    state.view[1] += (height - state.view[3]) / 2;
    constrain(state);
}

/** Attach once to a host, looking up its latest replacement figure per event. */
function listen(host) {
    host.addEventListener("keydown", event => {
        const state = figures.get(host);
        if (!state || event.target !== state.svg) return;
        const moves = {ArrowLeft:[-.1, 0], ArrowRight:[.1, 0], ArrowUp:[0, -.1], ArrowDown:[0, .1]};
        if (moves[event.key]) {
            state.view[0] += state.view[2] * moves[event.key][0];
            state.view[1] += state.view[3] * moves[event.key][1];
            constrain(state);
        } else if (event.key === "+" || event.key === "=") zoom(state, .8);
        else if (event.key === "-") zoom(state, 1.25);
        else if (event.key === "0" || event.key === "Home") {
            state.view = [...state.original];
            constrain(state);
        } else return;
        event.preventDefault();
    });
}

/** Restore keyboard navigation after rendering or a filtered SVG swap. */
export function initializeQualityChartControls(root = document) {
    if (lengthLabel) lengthLabel.hidden = true;
    for (const svg of root.querySelectorAll("svg[data-length-maximum]")) addLengthGuide(svg);
    for (const host of root.querySelectorAll("[data-quality-chart]")) {
        const svg = host.querySelector("svg");
        if (!svg || figures.get(host)?.svg === svg) continue;
        const view = (svg.getAttribute("viewBox") || "").trim().split(/\s+/).map(Number);
        if (view.length !== 4 || !view.every(Number.isFinite) || view[2] <= 0 || view[3] <= 0) continue;
        if (!figures.has(host)) listen(host);
        figures.set(host, {svg, original:[...view], view:[...view]});
        svg.setAttribute("tabindex", "0");
    }
}
