/** Present configured wiki reports and their recent execution history. */
import { jsx } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { JobHistoryDialogs, ReportLog, Routines } from "./status.jsx";

export function ReportsContents(context) {
    const { t } = context;
    return (
        <ul>
            <li>
                <a href="#tool-status-heading">{t.reports.panel}</a>
            </li>
            <li>
                <a href="#recent-events">{t.reports.log}</a>
            </li>
        </ul>
    );
}

export function Reports(context) {
    const { t } = context;
    return (
        <>
            <p class="page-description">{t.reports.intro}</p>
            {Routines(context)}
            <div id="report-history" tabindex="-1">
                {ReportLog(context)}
                {JobHistoryDialogs(context)}
            </div>
        </>
    );
}
