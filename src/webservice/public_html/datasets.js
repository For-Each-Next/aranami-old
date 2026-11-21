/** Accept only same-origin saved-file viewer links. */
function datasetURL(value) {
    const url = new URL(value, location.href);
    return url.origin === location.origin && url.pathname === "/data/"
        ? url
        : void 0;
}

/** Replace the page while preserving both the viewport and table scroll. */
function replaceDatasetViewer(previous, viewer, scroll, control) {
    const table = ".dataset-preview-table .table-scroll";
    const top = scroll.scrollTop;
    const left = previous.querySelector(table).scrollLeft;
    const label = control.getAttribute("aria-label");
    previous.replaceWith(viewer);
    window.aranamiComponents?.enhance(viewer);
    const next = [...viewer.querySelectorAll("a[data-dataset-page]")].find(
        link => link.getAttribute("aria-label") === label,
    );
    const focus = next || viewer.querySelector(control.matches(".page-size")
        ? ".page-size select" : "input[name=page]");
    focus?.focus({preventScroll: true});
    viewer.querySelector(table).scrollLeft = left;
    scroll.scrollTop = top;
}
/** Load one selected page at a time and release it when the dialog closes. */
function initializeDatasets() {
    let dialog;
    let opener;
    let controller;
    let requestNumber = 0;
    /** Replace the current page, aborting superseded requests without caching rows. */
    async function load(url, control, opening, updateHistory = true) {
        const request = ++requestNumber;
        controller?.abort();
        controller = new AbortController();
        control.setAttribute("aria-busy", "true");
        dialog?.setAttribute("aria-busy", "true");
        try {
            const response = await fetch(url, {
                signal: controller.signal,
                credentials: "same-origin",
                redirect: "error",
                headers: { Accept: "text/html" },
            });
            if (
                !response.ok ||
                (response.url && !datasetURL(response.url)) ||
                response.headers.get("Content-Type")?.split(";")[0].trim() !==
                    "text/html"
            )
                throw new Error("Saved data unavailable");
            const page = new DOMParser().parseFromString(
                await response.text(),
                "text/html",
            );
            if (request !== requestNumber) return;
            const viewer = page.querySelector("#dataset-viewer");
            const template = page.querySelector("#dataset-dialog-template");
            if (
                !viewer ||
                !template ||
                viewer.dataset.file !== url.searchParams.get("file") ||
                !Number.isSafeInteger(Number(viewer.dataset.page)) ||
                Number(viewer.dataset.page) < 1 ||
                viewer.querySelector("script, iframe, object, embed")
            )
                throw new Error("Invalid saved-data response");
            const standalone = !opening && control.closest("#dataset-viewer");
            if (standalone) {
                replaceDatasetViewer(standalone, viewer, document.scrollingElement, control);
                if (updateHistory && url.href !== location.href) history.pushState(null, "", url);
                return;
            }
            if (opening) {
                const previous = dialog;
                dialog = void 0;
                previous?.close();
                previous?.remove();
                dialog = template.content.firstElementChild?.cloneNode(true);
                if (dialog?.nodeName !== "DIALOG")
                    throw new Error("Missing saved-data dialog");
                opener = control;
                const opened = dialog;
                dialog.addEventListener("close", () => {
                    if (dialog !== opened) return;
                    ++requestNumber;
                    controller?.abort();
                    controller = void 0;
                    const returnFocus = opener;
                    opener = void 0;
                    dialog = void 0;
                    opened.remove();
                    if (returnFocus?.isConnected) returnFocus.focus();
                });
                document.body.append(dialog);
            }
            if (!dialog) throw new Error("Missing saved-data dialog");
            const body = dialog.querySelector("[data-dataset-content]");
            if (!body) throw new Error("Missing saved-data content");
            const identities = /* @__PURE__ */ new Map();
            for (const element of [
                viewer,
                ...viewer.querySelectorAll("[id]"),
            ]) {
                identities.set(element.id, `dataset-dialog-${element.id}`);
                element.id = identities.get(element.id);
            }
            for (const element of viewer.querySelectorAll(
                "[aria-labelledby]",
            )) {
                const label = element.getAttribute("aria-labelledby");
                element.setAttribute(
                    "aria-labelledby",
                    identities.get(label) || label,
                );
            }
            if (opening) {
                body.replaceChildren(viewer);
                window.aranamiComponents?.enhance(body);
                dialog.showModal();
            } else {
                replaceDatasetViewer(body.firstElementChild, viewer,
                    dialog.querySelector(".ui-dialog__body"), control);
            }
        } catch {
            if (request === requestNumber) location.assign(url.href);
        } finally {
            control.removeAttribute("aria-busy");
            if (request === requestNumber) {
                dialog?.removeAttribute("aria-busy");
                controller = void 0;
            }
        }
    }
    document.addEventListener("click", (event) => {
        const control = event.target.closest(
            "a[data-dataset-link],#dataset-dialog a[data-dataset-page],#dataset-viewer a[data-dataset-page]",
        );
        if (
            !control ||
            event.defaultPrevented ||
            event.ctrlKey ||
            event.metaKey ||
            event.shiftKey ||
            event.altKey ||
            event.button > 0 ||
            typeof fetch !== "function" ||
            typeof DOMParser !== "function" ||
            typeof AbortController !== "function" ||
            typeof HTMLDialogElement === "undefined" ||
            typeof HTMLDialogElement.prototype.showModal !== "function"
        )
            return;
        const url = datasetURL(control.href);
        if (!url) return;
        event.preventDefault();
        void load(url, control, control.hasAttribute("data-dataset-link"));
    });
    document.addEventListener("submit", event => {
        const form = event.target;
        if (!form.matches("#dataset-dialog .dataset-pagination form,#dataset-viewer .dataset-pagination form")) return;
        const url = datasetURL(form.action);
        if (!url) return;
        event.preventDefault();
        const fields = new URLSearchParams(new FormData(form));
        const entry = form.querySelector("input[name=page]");
        if (entry) fields.set("page", String(entry.valueAsNumber));
        url.search = fields.toString();
        void load(url, form, false);
    });
    window.addEventListener("popstate", () => {
        const viewer = document.getElementById("dataset-viewer");
        const url = datasetURL(location.href);
        if (viewer && url?.searchParams.get("file") === viewer.dataset.file)
            void load(url, viewer, false, false);
    });
}
export { initializeDatasets };
