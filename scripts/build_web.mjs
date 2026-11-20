/** Bundle the browser views with the production Vue runtime. */
import { build } from "esbuild";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
const destination = new URL("src/webservice/public_html/app.js", root);
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

if (process.argv.includes("--check")) {
    if ((await readFile(destination, "utf8")) !== bundle.text) {
        throw new Error("Refresh app.js with npm run build:web.");
    }
} else {
    await writeFile(destination, bundle.text);
}
