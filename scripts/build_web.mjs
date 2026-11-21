/** Bundle the browser views and the shared CSS-only Codex components. */
import { build } from "esbuild";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
const assets = new URL("src/webservice/public_html/", root);
const {
    outputFiles: [bundle],
} = await build({
    absWorkingDir: fileURLToPath(root),
    entryPoints: ["frontend/app.jsx"],
    bundle: true,
    define: {
        "process.env.NODE_ENV": '"production"',
        __VUE_OPTIONS_API__: "false",
        __VUE_PROD_DEVTOOLS__: "false",
        __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false",
    },
    format: "esm",
    jsxFactory: "jsx",
    jsxFragment: "Fragment",
    legalComments: "eof",
    minify: true,
    write: false,
});

const components = ["Button", "Card", "Checkbox", "Select", "TextArea", "TextInput"];
const [tokens, ...styles] = await Promise.all([
    "@wikimedia/codex-design-tokens/theme-wikimedia-ui-root.css",
    ...components.map(name => `@wikimedia/codex/dist/modules/Cdx${name}.css`),
].map(path => readFile(new URL(import.meta.resolve(path)), "utf8")));

// Keep compatible classes in existing templates and previously saved pages.
const sharedClasses = /\.cdx-(button|card|select|text-area|text-input)((?:--|__)[\w-]+)?(?![\w-])/g;
const chevrons = new Map(await Promise.all(
    ["codex-select.svg", "codex-select-disabled.svg"].map(async name => [
        (await readFile(new URL(`assets/icons/${name}`, assets), "utf8")).trim(),
        `/assets/icons/${name}`,
    ]),
));
const componentCss = styles.join("\n")
    .replace(sharedClasses, (selector, component, suffix = "") =>
        `:is(${selector}, .ui-${component}${suffix})`)
    // Serve the same chevrons locally under the site's image policy.
    .replace(/url\('data:image\/svg\+xml;utf8,([^']+)'\)/g, (_, encoded) => {
        const path = chevrons.get(decodeURIComponent(encoded));
        if (!path) throw new Error("Codex CSS uses an unrecognized SVG icon.");
        return `url("${path}")`;
    });
const codexCss =
    "/*! Wikimedia Codex (GPL-2.0-or-later). See /codex-license.html. */\n" +
    tokens + "\n" + componentCss;

for (const [name, content] of [["app.js", bundle.text], ["codex.css", codexCss]]) {
    const destination = new URL(name, assets);
    if (process.argv.includes("--check")) {
        if ((await readFile(destination, "utf8")) !== content) {
            throw new Error(`Refresh ${name} with npm run build:web.`);
        }
    } else {
        await writeFile(destination, content);
    }
}
