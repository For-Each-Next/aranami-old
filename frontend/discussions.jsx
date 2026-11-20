/** Display the saved discussion groups and update time. */
import { jsx, attribute, display, hasContent } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { ArticleCards } from "./articles.jsx";
import { SourceUpdated } from "./shared.jsx";

export function DiscussionsContents(context) {
    const { groups } = context;
    return (
        <ul>
            {(groups ?? []).map((section, sectionIndex) => (
                <li key={sectionIndex}>
                    <a href={"#" + attribute(section?.key)}>{display(section?.title)}</a>
                </li>
            ))}
        </ul>
    );
}

export function Discussions(context) {
    const { groups, unavailable } = context;
    return (
        <>
            {hasContent(unavailable) ? <p role="status">{display(unavailable)}</p> : null}
            {(groups ?? []).map((section, sectionIndex) => (
                <section
                    key={sectionIndex}
                    class="section-flat"
                    id={attribute(section?.key)}
                    aria-labelledby={attribute(section?.key) + "-heading"}
                >
                    <h2 id={attribute(section?.key) + "-heading"}>{display(section?.title)}</h2>
                    {ArticleCards({ ...context, section: section })}
                </section>
            ))}
            {SourceUpdated(context)}
        </>
    );
}
