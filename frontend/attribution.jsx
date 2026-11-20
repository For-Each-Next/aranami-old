/** Place authored license and credit documents in the page layout. */
import { jsx, display } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";

export function AttributionContents(context) {
    const { document, heading, t } = context;
    return (
        <ul>
            <li>
                <a href="#main">{display(heading)}</a>
            </li>
            {["content", "maintenance"].includes(document) ? (
                <li>
                    <a href="#attribution-images">{t.credits.images}</a>
                </li>
            ) : null}
            {document === "maintenance" ? (
                <li>
                    <a href="#template-correspondence">{t.credits.correspondence}</a>
                </li>
            ) : null}
            {document === "codex" ? (
                <li>
                    <a href="#vue-license">{"Vue"}</a>
                </li>
            ) : null}
            <li>
                <a href="/about/#credits">{t.about.credits}</a>
            </li>
        </ul>
    );
}

export function Attribution(context) {
    const { attribution_content, t } = context;
    return (
        <>
            <p class="page-description">{t.credits.original_language}</p>
            <div class="attribution-document" lang="en">
                {display(attribution_content)}
            </div>
        </>
    );
}
