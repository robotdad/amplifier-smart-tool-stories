import { build } from "esbuild";
import { readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
const bridge = await readFile(
  new URL(
    "../src/amplifier_smart_tool_stories/resources/bridge.js",
    import.meta.url,
  ),
  "utf8",
);
const result = await build({
  define: {
    __PREVIEW_BRIDGE__: JSON.stringify(bridge),
    __DOCUMENT_BRIDGE__: JSON.stringify(await readFile(new URL("../src/amplifier_smart_tool_stories/resources/document-view.js", import.meta.url), "utf8")),
  },
  stdin: {
    contents: [
      await readFile(new URL("app.js", import.meta.url), "utf8"),
      ...await Promise.all(["dashboard.js", "comparison.js", "provider-settings.js", "narration.js"].map(
        name => readFile(new URL("../src/amplifier_smart_tool_stories/resources/" + name, import.meta.url), "utf8"))),
    ].join("\n;\n"),
    resolveDir: new URL(".", import.meta.url).pathname,
    sourcefile: "shared-dashboard.js",
  },
  bundle: true,
  minify: true,
  write: false,
  format: "esm",
  target: "es2022",
  legalComments: "inline",
  metafile: true,
});
const resources = new URL("../src/amplifier_smart_tool_stories/resources/", import.meta.url);
const css = await readFile(new URL("dashboard.css", resources), "utf8");
const template = (await readFile(new URL("dashboard.html", resources), "utf8"))
  .replace(/<link rel="stylesheet" href="\/style.css"\s*\/>/, () => `<style>${css}</style>`)
  .replace(/<script src="\/[^"]+"><\/script>/g, "")
  .replace(/[ \t]+$/gm, "")
  .replace("</body>", "<!-- APP_SCRIPT --></body>");
const script = result.outputFiles[0].text.replaceAll("</script", "<\\/script");
await writeFile(
  new URL(
    "../src/amplifier_smart_tool_stories/resources/mcp_app.html",
    import.meta.url,
  ),
  template.replace(
    "<!-- APP_SCRIPT -->",
    () => `<script type="module">${script}</script>`,
  ),
);
const packages = new Set();
for (const input of Object.keys(result.metafile.inputs)) {
  const pieces = path
    .resolve(input)
    .split(`${path.sep}node_modules${path.sep}`);
  if (pieces.length < 2) continue;
  const tail = pieces.at(-1).split(path.sep);
  packages.add(
    pieces.slice(0, -1).join(`${path.sep}node_modules${path.sep}`) +
      `${path.sep}node_modules${path.sep}` +
      tail.slice(0, tail[0].startsWith("@") ? 2 : 1).join(path.sep),
  );
}
let licenses = "Third-party notices for the bundled Stories MCP Apps view\n\n";
for (const directory of [...packages].sort()) {
  const metadata = JSON.parse(
    await readFile(path.join(directory, "package.json"), "utf8"),
  );
  const license = (await readdir(directory)).find((name) =>
    /^licen[cs]e(?:\..*)?$/i.test(name),
  );
  if (!license) throw new Error(`Missing license for ${metadata.name}`);
  licenses += `${metadata.name} ${metadata.version}\n${await readFile(path.join(directory, license), "utf8")}\n\n`;
}
await writeFile(
  new URL(
    "../src/amplifier_smart_tool_stories/resources/mcp_app.LICENSE.txt",
    import.meta.url,
  ),
  licenses.replace(/[ \t]+$/gm, "").trimEnd() + "\n",
);
