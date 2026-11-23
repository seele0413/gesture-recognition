const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");
const industrialTheme = read("web/industrial-ui.css");
const glassTheme = read("web/comking-glass.css");

test("all management pages load the Comking glass theme after their existing styles", () => {
  const pages = [
    ["web/workflows.html", "/static/workflows.css", "/static/industrial-ui.css"],
    ["web/settings.html", "/static/styles.css", "/static/industrial-ui.css"],
    ["web/display-pages.html", "/static/display-pages.css", "/static/industrial-ui.css"],
  ];

  for (const [file, pageStyle, sharedStyle] of pages) {
    const html = read(file);
    const pageStyleIndex = html.indexOf(pageStyle);
    const sharedStyleIndex = html.indexOf(sharedStyle);
    const glassStyleIndex = html.indexOf("/static/comking-glass.css");
    assert.notEqual(pageStyleIndex, -1, file + " should keep its original page stylesheet");
    assert.ok(sharedStyleIndex > pageStyleIndex, file + " should keep the shared industrial compatibility stylesheet");
    assert.ok(glassStyleIndex > sharedStyleIndex, file + " should load the Comking glass theme last");
    assert.match(html, /<meta name="theme-color" content="#145da8">/);
  }
});

test("management pages use the Comking logo and Chinese-first headings", () => {
  for (const file of ["web/workflows.html", "web/settings.html", "web/display-pages.html"]) {
    const html = read(file);
    assert.match(html, /class="comking-logo-shell"/, file + " should render the logo surface");
    assert.match(html, /class="comking-logo"[^>]+src="https:\/\/img\.kompass\.com\//, file + " should use the found COMKING logo asset");
    assert.doesNotMatch(html, /class="settings-brand-mark">康<\/span>/, file + " should not render the placeholder 康 tile");
    assert.doesNotMatch(html, /<p class="eyebrow">[A-Z][A-Z ]+<\/p>/, file + " should not use decorative English eyebrow labels");
  }
});

test("Comking glass theme exposes Chinese typography, brand blue, and restrained glass surfaces", () => {
  for (const token of [
    "--ck-blue: #145da8",
    '"PingFang SC"',
    '"Microsoft YaHei UI"',
    "backdrop-filter: saturate(180%) blur(26px)",
    "rgba(255, 255, 255, .66)",
  ]) {
    assert.ok(glassTheme.includes(token), "missing Comking glass design token: " + token);
  }
  assert.match(glassTheme, /@media \(max-width: 720px\)/);
  assert.match(glassTheme, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(glassTheme, /\.canvas-node\[data-selected="true"\]/);
  assert.match(glassTheme, /\.pointer-calibration-overlay/);
  assert.match(glassTheme, /\.pointer-diagnostics-panel/);
  assert.ok(industrialTheme.includes("--ui-accent: #159b89"), "compatibility theme should remain available");
  assert.ok(glassTheme.includes("--ck-glass: rgba(255, 255, 255, .30)"), "glass base should be more transparent");
  assert.ok(glassTheme.includes("saturate(205%) blur(34px)"), "major glass surfaces should use stronger refraction");
  assert.ok(glassTheme.includes("radial-gradient(ellipse at 9% 8%"), "ambient background lighting should reveal transparency");
  assert.ok(glassTheme.includes("linear-gradient(145deg, #e7edf2 0%, #eff3f6 48%, #e7edef 100%)"), "latest glass background should use neutral gray-white tones");
  assert.ok(glassTheme.includes(".display-pages-page .page-node-actions .page-action.page-action-primary"), "default action needs a scoped high-contrast rule");
  assert.ok(glassTheme.includes("background: linear-gradient(180deg, #286da5 0%, #174f80 100%)"), "default action needs a solid readable background");
  assert.ok(glassTheme.includes("color: #fff;"), "default action should retain white text on its dark fill");
});

test("workflow interaction and pointer state hooks remain present", () => {
  const html = read("web/workflows.html");
  const css = read("web/workflows.css");
  const js = read("web/workflows.js");

  assert.match(html, /pointer-geometry\.js/);
  assert.match(html, /pointer-event-buffer\.js/);
  assert.match(html, /workflows\.js/);
  for (const selector of [
    '.canvas-node[data-selected="true"]',
    '.canvas-node[data-status="running"]',
    ".pointer-calibration-overlay",
    ".hand-pointer-cursor",
  ]) {
    assert.ok(css.includes(selector), "missing workflow interaction selector: " + selector);
  }
  for (const hook of [
    "handleHandPointer",
    "releaseHandPointer",
    "renderPointerCalibrationOverlay",
    "clientToWorld",
    "pointerGrabOffset",
    "drawEdgesForNode",
  ]) {
    assert.ok(js.includes(hook), "missing pointer/workflow behavior hook: " + hook);
  }
});

test("settings and page manager keep their existing application scripts", () => {
  assert.match(read("web/settings.html"), /\/static\/app\.js/);
  assert.match(read("web/display-pages.html"), /\/static\/display-pages\.js/);
});

test("workflow header separates system navigation from workflow actions and explains versions", () => {
  const html = read("web/workflows.html");
  const js = read("web/workflows.js");
  const navStart = html.indexOf('<nav class="workflow-primary-nav"');
  const navEnd = html.indexOf("</nav>", navStart);
  const actionsStart = html.indexOf('<div class="workflow-actions"');

  assert.match(html, /<title>康晋电气手势控制平台 · 工作流<\/title>/);
  assert.match(html, /<link rel="icon" href="https:\/\/img\.kompass\.com\//);
  assert.ok(navStart >= 0 && navEnd > navStart && navEnd < actionsStart, "system navigation should be in its own top header row");
  assert.match(html, /<small>手势控制平台<\/small>/);
  assert.match(html, /<span>版本 <small>历史记录<\/small><\/span>/);
  assert.match(html, /id="workflowVersion" aria-label="工作流保存版本"/);
  assert.match(js, /"v" \+ item\.version \+ \(isCurrent \? "（当前）" : "（历史）"\)/);
  assert.match(js, /历史版本 v" \+ item\.version/);
});

test("right-clicking a workflow node opens a closable floating parameter inspector", () => {
  const html = read("web/workflows.html");
  const js = read("web/workflows.js");
  const glass = read("web/comking-glass.css");

  assert.match(html, /id="workflowInspector" class="workflow-inspector" hidden/);
  assert.match(html, /id="inspectorClose"/);
  assert.match(js, /card\.addEventListener\("contextmenu"/);
  assert.match(js, /function openInspector\(nodeId\)/);
  assert.match(js, /function closeInspector\(\)/);
  assert.match(js, /ui\.inspectorClose\.addEventListener\("click", closeInspector\)/);
  assert.ok(glass.includes(".workflow-inspector[hidden]"), "inspector should stay hidden until requested");
  assert.ok(glass.includes("position: absolute;"), "inspector should float above the canvas rather than reserve a column");
});

test("display page default action uses the same neutral button style as edit and disable", () => {
  const js = read("web/display-pages.js");
  assert.match(js, /actions\.append\(makeButton\("编辑", \(\) => openEditor\(page\)\)\)/);
  assert.match(js, /actions\.append\(makeButton\("设为默认", \(\) => setDefault\(page\.page_id\)\)\)/);
  assert.match(js, /actions\.append\(makeButton\(page\.enabled \? "停用" : "启用", \(\) => toggleEnabled\(page\), ""\)\)/);
  assert.doesNotMatch(js, /makeButton\("设为默认"[^;]*page-action-primary/);
});


test("all pages use the unified Comking gesture control platform name", () => {
  const workflows = read("web/workflows.html");
  const settings = read("web/settings.html");
  const pages = read("web/display-pages.html");
  const shell = read("web/index.html");
  const factory = read("web/pages/factory.html");
  const product = read("web/pages/product.html");
  const promo = read("web/pages/promo.html");

  assert.match(workflows, /<title>康晋电气手势控制平台 · 工作流<\/title>/);
  assert.match(settings, /<title>康晋电气手势控制平台 · 设置<\/title>/);
  assert.match(pages, /<title>康晋电气手势控制平台 · 网页管理<\/title>/);
  assert.match(shell, /<title>康晋电气手势控制平台<\/title>/);
  assert.match(factory, /<title>康晋电气手势控制平台 · 智能制造<\/title>/);
  assert.match(product, /<title>康晋电气手势控制平台 · 产品中心<\/title>/);
  assert.match(promo, /<title>康晋电气手势控制平台 · 企业宣传片<\/title>/);
  assert.match(settings, /<small>手势控制平台 · 设置<\/small>/);
  assert.match(pages, /<small>手势控制平台 · 网页管理<\/small>/);
  for (const html of [workflows, settings, pages, shell, factory, product, promo]) {
    assert.doesNotMatch(html, /手势控制系统|展示控制系统/);
  }
});

test("all frontend pages use native platform system typography", () => {
  const base = read("web/styles.css");
  const industrial = read("web/industrial-ui.css");
  const glass = read("web/comking-glass.css");
  for (const [name, css] of [["base", base], ["industrial", industrial], ["glass", glass]]) {
    assert.ok(css.includes("system-ui, -apple-system, BlinkMacSystemFont"), name + " stylesheet should prefer native platform fonts");
    assert.ok(css.includes('"PingFang SC"'), name + " stylesheet should include a Chinese system-font fallback");
  }
  assert.doesNotMatch(glass, /"SF Pro Display"/, "do not bundle or force a font restricted to Apple-platform mockups");
});

test("workflow library fills the empty brand-side strip and action toolbar aligns to the trailing edge", () => {
  const html = read("web/workflows.html");
  const glass = read("web/comking-glass.css");
  assert.match(html, /<small>手势控制平台<\/small>/);
  assert.match(glass, /\.workflow-library\s*\{[\s\S]*?top:\s*-96px;/);
  assert.match(glass, /\.workflow-editor\s*\{[\s\S]*?grid-column:\s*2;/);
  assert.match(glass, /\.workflow-meta\s*\{[\s\S]*?width:\s*calc\(100% - 260px\);/);
  assert.match(glass, /\.workflow-actions\s*\{[\s\S]*?width:\s*max-content;[\s\S]*?margin-left:\s*auto;[\s\S]*?margin-right:\s*0;/);
  assert.match(glass, /@media \(max-width: 980px\)[\s\S]*?\.workflow-library\s*\{[\s\S]*?position:\s*static;/);
});

test("glass polish makes management surfaces lighter but leaves the workflow canvas material alone", () => {
  const glass = read("web/comking-glass.css");
  const start = glass.indexOf("2026-11-19 polish: platform naming");
  assert.ok(start >= 0, "latest polish section should exist");
  const polish = glass.slice(start);
  assert.match(polish, /\.workflow-library,[\s\S]*?background:[\s\S]*?rgba\(255,255,255,\.045\)/);
  assert.match(polish, /\.settings-panel,[\s\S]*?background:[\s\S]*?rgba\(255,255,255,\.045\)/);
  assert.doesNotMatch(polish, /\.canvas-viewport\s*\{/);
  assert.doesNotMatch(polish, /\.canvas-node\s*\{/);
  assert.doesNotMatch(polish, /\.canvas-node-header\s*\{/);
  assert.doesNotMatch(polish, /\.editor-toolbar\s*\{/);
});
