/** Mount the route specified by the server's localized saved-data model. */
import { createApp, Fragment } from "@vue/runtime-dom";
import { About, AboutContents } from "./about.jsx";
import { Attribution, AttributionContents } from "./attribution.jsx";
import { Consistency, ConsistencyContents } from "./consistency.jsx";
import { Dashboard, DashboardContents } from "./dashboard.jsx";
import { Dataset, DatasetContents } from "./dataset.jsx";
import { Discussions, DiscussionsContents } from "./discussions.jsx";
import { Error as ErrorPage } from "./error.jsx";
import { Logs, LogsContents } from "./logs.jsx";
import { Maintenance } from "./maintenance.jsx";
import { Newsletter, NewsletterContents } from "./newsletter.jsx";
import { QualityAnalysis, QualityAnalysisContents } from "./quality_analysis.jsx";
import { QualityAuthorship, QualityAuthorshipContents } from "./quality_authorship.jsx";
import { Reports, ReportsContents } from "./reports.jsx";
import { Uptime } from "./status.jsx";
import { jsx, assetUrl, defaultContents, display, iconHref, restoreMarkup } from "./rendering.js";

const pages = {
    about: [About, AboutContents],
    attribution: [Attribution, AttributionContents],
    consistency: [Consistency, ConsistencyContents],
    dashboard: [Dashboard, DashboardContents],
    dataset: [Dataset, DatasetContents],
    discussions: [Discussions, DiscussionsContents],
    error: [ErrorPage, defaultContents],
    logs: [Logs, LogsContents],
    maintenance: [Maintenance, defaultContents],
    newsletter: [Newsletter, NewsletterContents],
    quality_analysis: [QualityAnalysis, QualityAnalysisContents],
    quality_authorship: [QualityAuthorship, QualityAuthorshipContents],
    reports: [Reports, ReportsContents],
};

function Navigation({ context }) {
    const { t, navigation } = context;
    const primary = [
        ["/", t.nav.dashboard],
        ["/discussions/", t.discussions.heading],
        ["/quality-analysis/", t.quality_analysis.heading],
    ];
    const tools = [
        ["/reports/", t.nav.reports],
        ["/checks/", t.nav.checks],
        ["/newsletter/", t.nav.newsletter],
    ];
    const languages = navigation?.languages ?? [
        { url: "?lang=en", tag: "en", label: "English" },
        { url: "?lang=zh-hans", tag: "zh-Hans", label: "简体中文" },
        { url: "?lang=zh-hant", tag: "zh-Hant", label: "繁體中文" },
    ];
    const current = (href) => (navigation?.path === href ? "page" : undefined);
    return (
        <header class="masthead">
            <div class="shell header-inner">
                <a href="/" class="brand">
                    <img
                        src={assetUrl(context, "assets/images/aranami-wordmark.png")}
                        width="205"
                        height="47"
                        alt="Aranami"
                    />
                </a>
                <nav class="global-navigation" aria-label={t.nav.global}>
                    {primary.map(([href, label]) => (
                        <a key={href} href={href} aria-current={current(href)}>
                            {label}
                        </a>
                    ))}
                    <details class="navigation-tools">
                        <summary>{t.nav.tools}</summary>
                        <ul class="navigation-tools-list">
                            {tools.map(([href, label]) => (
                                <li key={href}>
                                    <a href={href} aria-current={current(href)}>
                                        {label}
                                    </a>
                                </li>
                            ))}
                        </ul>
                    </details>
                </nav>
                <nav class="language-switcher" aria-label={t.nav.language}>
                    <details class="navigation-tools language-menu">
                        <summary aria-label={t.nav.language}>
                            <svg
                                class="language-icon"
                                width="20"
                                height="20"
                                viewBox="0 0 20 20"
                                aria-hidden="true"
                            >
                                <use href={iconHref(context, "language")} />
                            </svg>
                            <span class="language-label">{t.nav.language}</span>
                        </summary>
                        <ul class="navigation-tools-list">
                            {languages.map(({ url, tag, label, current }) => (
                                <li key={tag}>
                                    <a
                                        href={url}
                                        lang={tag}
                                        hreflang={tag}
                                        aria-current={current ? "true" : undefined}
                                    >
                                        {label}
                                    </a>
                                </li>
                            ))}
                        </ul>
                    </details>
                </nav>
            </div>
        </header>
    );
}

function Layout({ context, view, contents }) {
    const { t, heading, navigation, footer, project_link } = context;
    return (
        <>
            <a href="#main" class="skip">
                {t.nav.skip}
            </a>
            <Navigation context={context} />
            <div class="shell page-layout">
                <aside class="contents-panel">
                    <nav class="page-toc contents-desktop" aria-label={t.nav.contents}>
                        <p class="contents-heading">{t.nav.contents}</p>
                        {contents(context)}
                    </nav>
                    <details class="contents-mobile navigation-tools">
                        <summary>
                            <span class="contents-icon" aria-hidden="true">
                                ☰
                            </span>
                            {t.nav.contents}
                        </summary>
                        <nav class="page-toc" aria-label={t.nav.contents}>
                            {contents(context)}
                        </nav>
                    </details>
                </aside>
                <main id="main" tabindex="-1">
                    <div class="page-heading">
                        <h1>{heading}</h1>
                    </div>
                    <div class="page-content">{view(context)}</div>
                </main>
            </div>
            <footer>
                <div class="shell footer-inner">
                    <p class="footer-uptime">{footer && Uptime(context)}</p>
                    <nav class="footer-links" aria-label="Aranami">
                        <a
                            href="/about/"
                            aria-current={navigation?.path === "/about/" ? "page" : undefined}
                        >
                            {t.nav.about}
                        </a>
                        {display(project_link)}
                    </nav>
                </div>
            </footer>
        </>
    );
}

async function start() {
    const boot = document.getElementById("aranami-page");
    const host = document.getElementById("aranami-app");
    const { schema, page, context, markup, scripts } = JSON.parse(boot.textContent);
    if (schema !== 1 || !Object.hasOwn(pages, page)) throw new Error("Unsupported page model");
    const [view, contents] = pages[page];
    restoreMarkup(context, markup);
    const { nav, ops } = context.t;
    Object.assign(document.body.dataset, {
        headingCopyLabel: nav.copy_section_link,
        headingCopySuccess: nav.section_link_copied,
        headingCopyFailure: nav.section_link_fallback,
        headingPermalinkLabel: nav.section_permalink,
        headingPagePermalinkLabel: nav.page_permalink,
        headingCopyClose: ops.close,
    });
    // Mount off-document so the HTML fallback stays available if rendering fails.
    const rendered = document.createElement("div");
    const app = createApp({
        render: () => <Layout context={context} view={view} contents={contents} />,
    });
    app.config.errorHandler = (error) => {
        throw error;
    };
    app.mount(rendered);
    rendered.id = host.id;
    rendered.dataset.rendered = "vue";
    host.replaceWith(rendered);
    boot.remove();
    if (location.hash) {
        try {
            document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView();
        } catch {
            // Ignore malformed fragment escapes.
        }
    }
    await Promise.all(scripts.map((script) => import(script)));
    rendered.dataset.ready = "true";
}

start().catch((error) => console.error("Could not initialize Aranami", error));
