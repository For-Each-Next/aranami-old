/** Render a localized request error with a link to the dashboard. */
import { jsx, iconHref, display } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";

export function Error(context) {
    const { message, t } = context;
    return (
        <>
            <div class="ui-message ui-message--error" role="alert">
                <svg class="ui-icon ui-message__icon" viewBox="0 0 20 20" aria-hidden="true">
                    <use href={iconHref(context, "message-error")}></use>
                </svg>
                <div class="ui-message__content">{display(message)}</div>
            </div>
            <p>
                <a href="/">{t.nav.dashboard}</a>
            </p>
        </>
    );
}
