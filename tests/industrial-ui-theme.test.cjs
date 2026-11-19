const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");
const theme = read("web/industrial-ui.css");

test("all management pages load the shared industrial theme after their page styles", () => {
  const pages = [
    ["web/workflows.html", "/static/workflows.css", "/static/industrial-ui.css"],
    ["web/settings.html", "/static/styles.css", "/static/industrial-ui.css"],
    ["web/display-pages.html", "/static/display-pages.css", "/static/industrial-ui.css"],
  ];

  for (const [file, pageStyle, sharedStyle] of pages) {
    const html = read(file);
    const pageStyleIndex = html.indexOf(pageStyle);
    const sharedStyleIndex = html.indexOf(sharedStyle);
    assert.notEqual(pageStyleIndex, -1, file + " should keep its original page stylesheet");
    assert.ok(sharedStyleIndex > pageStyleIndex, file + " should load the shared theme after existing styles");
    assert.match(html, /<meta name="theme-color" content="#111827">/);
  }
});

test("shared theme exposes the approved industrial SaaS design tokens", () => {
  for (const token of [
    "--ui-bg: #f3f5f8",
    "--ui-nav: #111827",
    "--ui-accent: #159b89",
    "--ui-radius: 12px",
    "--ui-surface: #ffffff",
  ]) {
    assert.ok(theme.includes(token), "missing design token: " + token);
  }
  assert.match(theme, /:focus-visible/);
  assert.match(theme, /@media \(max-width: 720px\)/);
  assert.match(theme, /@media \(prefers-reduced-motion: reduce\)/);
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
