/** Show metadata, schema and preview rows for a selected dataset. */
import { jsx, attribute, defaultContents, display, hasContent } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { TablePager } from "./shared.jsx";

export function DatasetContents(context) {
    const { dataset, t } = context;
    return hasContent(dataset) ? (
        <ul>
            <li>
                <a href="#dataset-metadata">{t.data.metadata}</a>
            </li>
            <li>
                <a href="#dataset-schema">{t.data.schema}</a>
            </li>
            <li>
                <a href="#dataset-preview">{t.data.preview}</a>
            </li>
        </ul>
    ) : (
        display(defaultContents(context))
    );
}

export function Dataset(context) {
    const { dataset, language_tag, t } = context;
    return hasContent(dataset) ? (
        <>
            <div
                id="dataset-viewer"
                data-file={attribute(dataset?.file)}
                data-page={attribute(dataset?.page)}
                data-close={t.ops.close}
            >
                <p class="page-description">{t.data.description}</p>
                <section class="section-flat" aria-labelledby="dataset-metadata">
                    <h2 id="dataset-metadata">{t.data.metadata}</h2>
                    <div class="ui-table">
                        <div
                            class="ui-table__table-wrapper table-scroll"
                            tabindex="0"
                            role="region"
                            aria-label={t.data.metadata}
                        >
                            <table class="ui-table__table" data-no-pagination="">
                                <caption class="visually-hidden">{display(dataset?.name)}</caption>
                                <tbody>
                                    {(dataset?.facts ?? []).map((fact, factIndex) => (
                                        <tr key={factIndex}>
                                            <th scope="row">{display(fact?.label)}</th>
                                            <td>
                                                {fact?.value == null
                                                    ? display(t.data.unknown)
                                                    : display(fact?.value)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </section>
                <section class="section-flat" aria-labelledby="dataset-schema">
                    <h2 id="dataset-schema">{t.data.schema}</h2>
                    <div class="ui-table">
                        <div
                            class="ui-table__table-wrapper table-scroll"
                            tabindex="0"
                            role="region"
                            aria-label={t.data.schema}
                        >
                            <table class="ui-table__table" data-no-pagination="">
                                <caption class="visually-hidden">{t.data.schema}</caption>
                                <thead>
                                    <tr>
                                        <th scope="col">{t.data.column}</th>
                                        <th scope="col">{t.data.type}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(dataset?.schema ?? []).map(([name, dtype], nameIndex) => (
                                        <tr key={nameIndex}>
                                            <th scope="row">
                                                <code>{display(name)}</code>
                                            </th>
                                            <td>
                                                <code>{display(dtype)}</code>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </section>
                <section class="section-flat" aria-labelledby="dataset-preview">
                    <h2 id="dataset-preview">{t.data.preview}</h2>
                    <div class="ui-table dataset-preview-table">
                        <div
                            class="ui-table__table-wrapper table-scroll"
                            tabindex="0"
                            role="region"
                            aria-label={t.data.preview}
                        >
                            <table class="ui-table__table">
                                <caption class="visually-hidden">{display(dataset?.name)}</caption>
                                <thead>
                                    <tr>
                                        {(dataset?.columns ?? []).map((name, nameIndex) => (
                                            <th key={nameIndex} scope="col">
                                                <code>{display(name)}</code>
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {(dataset?.cells ?? []).map((row, rowIndex) => (
                                        <tr key={rowIndex}>
                                            {(row ?? []).map((cell, cellIndex) => (
                                                <td key={cellIndex}>
                                                    {cell?.value == null ? (
                                                        <span class="context">
                                                            {display(t.data.null)}
                                                        </span>
                                                    ) : (
                                                        display(cell?.value)
                                                    )}
                                                </td>
                                            ))}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <TablePager paging={dataset} action="/data/" css="dataset-pagination"
                                fields={{ file: dataset.file, lang: language_tag }}
                                title={t.data.preview} dataset={true} t={t} />
                </section>
            </div>
        </>
    ) : (
        <p class="page-description">{t.data.choose}</p>
    );
}
