/** Adapt the saved presentation data to Vue's text, markup and attributes. */
import { createStaticVNode, h } from "@vue/runtime-dom";

const authoredHtml = Symbol("authoredHtml");

/** Keep Vue fragment children in an array, including a single text node. */
export function jsx(type, props, ...children) {
    return h(type, props, children);
}

/** Mark exactly the values the server constructed as escaped HTML. */
export function restoreMarkup(context, paths) {
    for (const path of paths) {
        const parent = path.slice(0, -1).reduce((value, key) => value[key], context);
        const key = path.at(-1);
        parent[key] = { [authoredHtml]: parent[key] };
    }
}

export function display(value) {
    return value?.[authoredHtml] === undefined
        ? (value ?? "")
        : createStaticVNode(value[authoredHtml], 1);
}

export function attribute(value) {
    return value == null ? "" : String(value);
}

export function hasContent(value) {
    if (Array.isArray(value)) return value.length > 0;
    if (value && typeof value === "object")
        return value[authoredHtml] !== undefined || Object.keys(value).length > 0;
    return Boolean(value);
}

export function format(template, values) {
    return template.replace(/\{(\w+)\}/g, (field, name) => values[name] ?? field);
}

export function assetUrl(context, name) {
    return context.assets[name] ?? "/" + name;
}

export function iconHref(context, symbol) {
    return assetUrl(context, "assets/icons/report-icons.svg") + "#" + symbol;
}

export function clockAttributes(clock) {
    return {
        "data-server-time": clock.server_time,
        "data-schedule-expires": clock.expires,
        "data-schedule-stale": clock.stale,
        "data-clock-messages": clock.messages,
    };
}

/** Keep timestamps visible when the saved evidence contains no source link. */
export function OptionalLink({ href, title }, { slots }) {
    const children = slots.default();
    return href ? h("a", { href, title }, children) : children;
}

export function defaultContents({ heading }) {
    return h("ul", [h("li", [h("a", { href: "#main" }, heading)])]);
}
