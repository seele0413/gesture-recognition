// Optional browser integration suite. Requires Playwright and Microsoft Edge.
// Run against a local development server; only this suite's own fixtures are removed.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const base = process.env.GESTURE_TEST_URL || "http://127.0.0.1:8765";
const output = path.join(__dirname, "../../data/usage-flow-qa");
const ids = [];
const results = [];
const errors = [];
const versionRequests = [];
const stamp = Date.now().toString(36);
let browser;
let context;
let admin;
async function until(check, message) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 80));
  }
  throw new Error(message);
}
async function check(name, run) {
  await run();
  results.push(name);
  console.log("PASS " + name);
}
async function api(route, options = {}) {
  const response = await context.request.fetch(base + route, options);
  const data = await response.json();
  assert.ok(response.ok(), route + ": " + JSON.stringify(data));
  return data;
}
function fixture(id, name) {
  const now = new Date().toISOString();
  return {
    schema_version: 1, id, name, description: "", enabled: false, version: 1,
    trigger: { type: "gesture_trigger", gesture: "Open_Palm", page_scope: "promo" },
    nodes: [
      { id: "play", type: "action", action: "video.play", params: {}, timeout_ms: 3000,
        on_error: "stop", position: { x: 170, y: 80 } },
      { id: "end", type: "end", params: {}, position: { x: 470, y: 80 } },
    ], edges: [{ source: "play", target: "end" }], created_at: now, updated_at: now,
  };
}
async function choose(value) {
  await admin.locator("#unsavedDialog").waitFor({ state: "visible" });
  await admin.locator('#unsavedDialog button[value="' + value + '"]').click();
  await admin.locator("#unsavedDialog").waitFor({ state: "hidden" });
}
async function selectWorkflow(id) {
  await until(() => admin.evaluate(() => !document.querySelector(".workflow-toolbar").inert), "editor still loading");
  await admin.locator("#workflowsTab").click();
  await admin.locator("#workflowSearch").fill("");
  await admin.locator("#gestureMapScope").selectOption("all");
  await admin.locator('[data-workflow-id="' + id + '"]').click();
  await until(() => admin.evaluate((id) => workflow?.id === id
    && !document.querySelector(".workflow-toolbar").inert
    && !draftState.dirty(workflow, workflowIsDraft), id), "workflow did not load");
}
(async () => {
  fs.mkdirSync(output, { recursive: true });
  browser = await chromium.launch({ channel: "msedge", headless: true });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  context.setDefaultTimeout(12000);
  context.setDefaultNavigationTimeout(15000);
  context.on("page", (page) => {
    page.on("pageerror", (error) => { errors.push(error.message); console.error("PAGE ERROR", error.message); });
    page.on("request", (request) => { if (request.url().includes("/versions")) versionRequests.push(request.url()); });
  });
  await context.route("https://img.kompass.com/**", (route) => route.abort());
  const a = "usage-qa-a-" + stamp;
  const b = "usage-qa-b-" + stamp;
  for (const [id, name] of [[a, "宣传片播放"], [b, "另一个播放流程"]]) {
    await api("/api/workflows", { method: "POST", data: fixture(id, name) });
    ids.push(id);
  }
  const lockId = "usage-qa-lock-" + stamp;
  const sequenceId = "usage-qa-sequence-" + stamp;
  const lockFlow = fixture(lockId, "主控欢迎流程");
  lockFlow.trigger = { type: "controller_locked" };
  const sequenceFlow = fixture(sequenceId, "工厂手势序列");
  sequenceFlow.trigger = { type: "gesture_sequence_trigger", gestures: ["Open_Palm", "Thumb_Up"],
    sequence_window_ms: 5000, page_scope: "factory" };
  for (const definition of [lockFlow, sequenceFlow]) {
    await api("/api/workflows", { method: "POST", data: definition });
    ids.push(definition.id);
  }
  const display = await context.newPage();
  await display.goto(base, { waitUntil: "domcontentloaded" });
  await until(async () => (await api("/api/workflow-status")).display_ready, "display not ready");
  await check("management opens separately and preserves the display executor", async () => {
    const popup = context.waitForEvent("page");
    await display.locator("#openManagement").click();
    admin = await popup;
    await admin.waitForURL(base + "/settings");
    await admin.locator("#rtspUrl").waitFor();
    assert.equal(await admin.locator(".usage-status").count(), 0);
    assert.equal((await api("/api/workflow-status")).display_ready, true);
    await admin.locator('.settings-header-tools a[href="/workflows"]').click();
    await admin.locator("#workflowName").waitFor();
    await selectWorkflow(a);
    await admin.screenshot({ path: path.join(output, "workflows-in-progress.png"), fullPage: true });
    await admin.locator("#workflowName").fill("宣传片播放 · 未保存");
    await display.locator("#openManagement").click();
    assert.match(admin.url(), /\/workflows$/);
    assert.equal(await admin.locator("#workflowName").inputValue(), "宣传片播放 · 未保存");
    assert.equal(context.pages().length, 2);
    await admin.locator(".workflow-primary-nav [data-open-display]").click();
    assert.equal(context.pages().length, 2);
    assert.equal((await api("/api/workflow-status")).display_ready, true);
  });
  await check("a rejected second display has an actionable message and leaves the owner running", async () => {
    const duplicate = await context.newPage();
    await duplicate.goto(base, { waitUntil: "domcontentloaded" });
    await until(async () => (await duplicate.locator("#displayShellLabel").textContent()).includes("已有大屏"), "duplicate display not explained");
    assert.equal(await duplicate.locator("#retryDisplay").isVisible(), true);
    assert.equal((await api("/api/workflow-status")).display_ready, true);
    await duplicate.close();
  });
  await check("cancel and failed save preserve edits; successful save continues navigation", async () => {
    await admin.locator('.workflow-primary-nav a[href="/settings"]').click();
    await choose("cancel");
    assert.equal(await admin.locator("#workflowName").inputValue(), "宣传片播放 · 未保存");
    await admin.route("**/api/workflows/" + a, async (route) => {
      if (route.request().method() === "PUT") await route.fulfill({ status: 400, json: { detail: "验收模拟保存失败" } });
      else await route.continue();
    });
    await admin.locator('.workflow-primary-nav a[href="/settings"]').click();
    await choose("save");
    await until(async () => (await admin.locator("#validationMessage").textContent()).includes("模拟保存失败"), "save error missing");
    assert.match(admin.url(), /\/workflows$/);
    assert.equal(await admin.locator("#workflowSaveState").getAttribute("data-dirty"), "true");
    await admin.unroute("**/api/workflows/" + a);
    await admin.locator('.workflow-primary-nav a[href="/settings"]').click();
    await choose("save");
    await admin.waitForURL(base + "/settings");
    assert.equal((await api("/api/workflows/" + a)).workflow.name, "宣传片播放 · 未保存");
    await admin.locator('.settings-header-tools a[href="/workflows"]').click();
    await selectWorkflow(a);
  });
  await check("discard navigates without a second native prompt and does not save", async () => {
    await admin.locator("#workflowName").fill("不应被保存的名称");
    let nativePrompts = 0;
    const onDialog = async (dialog) => { nativePrompts++; await dialog.dismiss(); };
    admin.on("dialog", onDialog);
    await admin.locator('.workflow-primary-nav a[href="/settings"]').click();
    await choose("discard");
    await admin.waitForURL(base + "/settings");
    admin.off("dialog", onDialog);
    assert.equal(nativePrompts, 0);
    assert.equal((await api("/api/workflows/" + a)).workflow.name, "宣传片播放 · 未保存");
    await admin.locator('.settings-header-tools a[href="/workflows"]').click();
    await selectWorkflow(a);
  });
  await check("enable conflicts are reported; disabling does not save invalid local edits", async () => {
    await admin.locator("#toggleWorkflow").click();
    await until(async () => (await admin.locator("#workflowSaveState").textContent()).startsWith("已启用"), "flow not enabled");
    await selectWorkflow(b);
    await admin.locator("#toggleWorkflow").click();
    await until(async () => (await admin.locator("#validationMessage").textContent()).includes("冲突"), "enable conflict missing");
    assert.equal((await api("/api/workflows/" + b)).workflow.enabled, false);
    await selectWorkflow(a);
    await admin.locator("#workflowName").fill("");
    await admin.locator("#toggleWorkflow").click();
    await until(async () => !(await api("/api/workflows/" + a)).workflow.enabled, "flow not disabled");
    assert.equal(await admin.locator("#workflowName").inputValue(), "");
    assert.equal(await admin.locator("#workflowSaveState").getAttribute("data-dirty"), "true");
    assert.equal((await api("/api/workflows/" + a)).workflow.name, "宣传片播放 · 未保存");
  });
  await check("list switching protects edits while backend history remains available", async () => {
    await admin.locator('[data-workflow-id="' + b + '"]').click();
    await choose("cancel");
    assert.equal(await admin.locator("#workflowName").inputValue(), "");
    await admin.locator('[data-workflow-id="' + b + '"]').click();
    await choose("discard");
    await until(() => admin.evaluate((id) => workflow?.id === id && !document.querySelector(".workflow-toolbar").inert, b), "list selection not completed");
    await selectWorkflow(a);
    assert.equal(await admin.locator("#workflowVersion, #workflowSelect, #gestureWorkflowMap").count(), 0);
    const versions = await api("/api/workflows/" + a + "/versions");
    assert.ok(versions.versions.length >= 2);
  });
  await check("reload warns about dirty changes and cancelling keeps the editor", async () => {
    await until(() => admin.evaluate(() => !savePromise && !document.querySelector(".workflow-toolbar").inert), "save still running");
    await admin.locator("#workflowName").fill("刷新保护");
    await until(() => admin.evaluate(() => draftState.dirty(workflow, workflowIsDraft)), "edit did not become dirty");
    const dialogPromise = admin.waitForEvent("dialog");
    const reload = admin.reload({ waitUntil: "domcontentloaded" }).catch(() => {});
    const dialog = await dialogPromise;
    assert.equal(dialog.type(), "beforeunload");
    await dialog.dismiss();
    await reload;
    assert.equal(await admin.locator("#workflowName").inputValue(), "刷新保护");
    await admin.locator("#saveWorkflow").click();
    await until(async () => await admin.locator("#workflowSaveState").getAttribute("data-dirty") === "false", "save not completed");
  });
  await check("page manager shortcuts filter mappings and prefill new workflow scope", async () => {
    await admin.locator('.workflow-primary-nav a[href="/display-pages"]').click();
    await admin.locator('a[href="/workflows?page_scope=product"]').click();
    await admin.waitForURL(/\/workflows\?page_scope=product$/);
    await until(async () => await admin.locator("#gestureMapScope").inputValue() === "product", "scope filter not initialized");
    await admin.locator("#newWorkflow").click();
    await until(async () => await admin.locator(".trigger-page-scope-select").inputValue() === "product", "new workflow scope incorrect");
    const created = await admin.evaluate(() => workflow.id);
    ids.push(created);
    await until(() => admin.evaluate(() => !document.querySelector(".workflow-toolbar").inert), "new workflow still loading");
    assert.equal((await api("/api/workflows/" + created)).workflow.trigger.page_scope, "product");
  });
  await check("AI preview application protects ordinary edits before replacing the canvas", async () => {
    await admin.locator("#workflowName").fill("AI 替换前的修改");
    const preview = fixture("usage-qa-ai-" + stamp, "AI 草稿");
    await admin.locator("#generateWorkflow").click();
    await admin.evaluate((definition) => {
      generatedWorkflowPreview = { workflow: definition, validation_errors: [] };
      ui.workflowGeneratorResult.hidden = false;
      ui.applyGeneratedWorkflow.disabled = false;
    }, preview);
    await admin.locator("#applyGeneratedWorkflow").click();
    await choose("cancel");
    assert.equal(await admin.locator("#workflowName").inputValue(), "AI 替换前的修改");
    await admin.locator("#applyGeneratedWorkflow").click();
    await choose("discard");
    await until(() => admin.evaluate(() => workflowIsDraft && workflow?.name === "AI 草稿"), "AI preview was not applied");
    assert.equal(await admin.locator("#workflowName").inputValue(), "AI 草稿");
    assert.equal(await admin.locator("#workflowSaveState").getAttribute("data-dirty"), "true");
    await admin.locator("#saveWorkflow").click();
    await until(() => admin.evaluate(() => !savePromise && !workflowIsDraft
      && !draftState.dirty(workflow, workflowIsDraft)), "AI draft not saved");
    ids.push(preview.id);
    assert.equal((await api("/api/workflows/" + preview.id)).workflow.enabled, false);
    await admin.locator("#workflowName").fill("AI 草稿的下一次修改");
    await admin.locator('.workflow-primary-nav a[href="/settings"]').click();
    await choose("discard");
    await admin.waitForURL(base + "/settings");
  });
  await check("SUSPECT identity and lock-frame feedback survive page refresh", async () => {
    let controller = { state: "suspect", track_id: "person-1", identity_confirmed: true };
    await admin.route("**/api/status", (route) => route.fulfill({ json: {
      state: "running", frame_fresh: true, tracks: [], controller, vision: {}, pointer_mode_enabled: false,
    } }));
    await admin.reload({ waitUntil: "domcontentloaded" });
    await until(async () => (await admin.locator("#controllerStatus").textContent()).includes("原主控手部已确认"), "confirmed suspect missing");
    controller = { ...controller, identity_confirmed: false };
    await until(async () => (await admin.locator("#controllerStatus").textContent()).includes("身份待确认"), "unconfirmed suspect missing");
    controller = { state: "unlocked", lock_progress: 2, lock_required_frames: 4, lock_window_frames: 7 };
    await display.route("**/api/status", (route) => route.fulfill({ json: {
      state: "running", frame_fresh: true, controller, tracks: [], vision: {},
    } }));
    await until(async () => (await display.frameLocator("#displayPageFrame").locator("#cameraStatusLabel").textContent()).includes("2/4（最近 7 帧）"), "player lock progress is not data-driven");
    await admin.unroute("**/api/status");
    await display.unroute("**/api/status");
    await admin.reload({ waitUntil: "domcontentloaded" });
  });
  await check("existing gesture feedback and console delivery survive status panel removal", async () => {
    let events;
    const logs = [];
    admin.on("console", (message) => { if (message.text().startsWith("[gesture-control]")) logs.push(message.text()); });
    await admin.routeWebSocket("**/ws/events", (route) => { events = route; route.connectToServer(); });
    await admin.reload({ waitUntil: "domcontentloaded" });
    await until(() => Boolean(events), "feedback socket not connected");
    events.send(JSON.stringify({ type: "gesture", target_id: "person-1", target_name: "主控", handedness: "Right",
      gesture: "Open_Palm", confidence: 0.9, timestamp_ms: Date.now(), action: "none",
      action_triggered: false, workflow_triggered: true, workflow_handled: true,
      landmarks: Array.from({ length: 21 }, () => ({ x: 0.5, y: 0.5, z: 0 })) }));
    await until(async () => await admin.locator("#eventList .event-item").count() > 0, "gesture delivery missing");
    assert.ok(logs.length > 0);
    assert.equal(await admin.locator(".usage-status").count(), 0);
  });
  await check("pointer warning is visible outside advanced tools and can disable pointer mode", async () => {
    await admin.locator('.settings-header-tools a[href="/workflows"]').click();
    await selectWorkflow(a);
    await api("/api/pointer/mode", { method: "POST", data: { enabled: true } });
    await admin.locator("#pointerModeNotice").waitFor({ state: "visible" });
    await admin.locator("#disablePointerMode").click();
    await admin.locator("#pointerModeNotice").waitFor({ state: "hidden" });
    assert.equal((await api("/api/pointer/mode")).enabled, false);
  });
  await check("local/external display switches retain management entry and executor connection", async () => {
    await display.evaluate(() => navigatePage("factory"));
    assert.equal((await api("/api/workflow-status")).display_page_id, "factory");
    assert.equal(await display.locator("#openManagement").isVisible(), true);
    await context.route("https://www.zhcomking.com/", (route) => route.fulfill({
      contentType: "text/html", body: "<html><body>External display fixture</body></html>",
    }));
    await display.evaluate(() => navigatePage("company_website"));
    assert.equal((await api("/api/workflow-status")).display_page_id, "company_website");
    assert.equal(await display.locator("#openManagement").isVisible(), true);
    await display.locator("#openManagement").click();
    assert.equal(context.pages().length, 2);
    await display.evaluate(() => navigatePage("promo"));
    assert.equal((await api("/api/workflow-status")).display_ready, true);
  });
  await check("unified workflow list includes lifecycle and sequence triggers with working search", async () => {
    await admin.locator("#workflowsTab").click();
    await admin.locator("#workflowSearch").fill("主控欢迎");
    assert.equal(await admin.locator(".workflow-list-item").count(), 1);
    await admin.locator('[data-workflow-id="' + lockId + '"]').click();
    await until(async () => await admin.locator("#triggerType").inputValue() === "controller_locked", "lock flow missing");
    await admin.locator("#workflowSearch").fill("工厂手势序列");
    await admin.locator('[data-workflow-id="' + sequenceId + '"]').click();
    await until(async () => await admin.locator("#triggerType").inputValue() === "gesture_sequence_trigger", "sequence flow missing");
    assert.equal(await admin.locator(".trigger-page-scope-select").inputValue(), "factory");
    await selectWorkflow(a);
  });
  await check("categorized nodes, single-click parameters, dragging and linking preserve editing state", async () => {
    await selectWorkflow(a);
    await admin.locator("#nodesTab").click();
    assert.equal(await admin.evaluate(() => draftState.dirty(workflow, workflowIsDraft)), false);
    const ppt = admin.locator(".node-category").filter({ has: admin.locator("summary", { hasText: /^PPT/ }) });
    assert.equal(await ppt.getAttribute("open"), null);
    await admin.locator("#nodeSearch").fill("延迟");
    assert.equal(await admin.locator("#actionLibrary .library-node").count(), 1);
    await admin.locator('[data-node-type="delay"]').click();
    await admin.locator("#workflowInspector").waitFor({ state: "visible" });
    const delayId = await admin.evaluate(() => selectedNodeId);
    await admin.locator('#inspectorContent input[type="number"]').first().fill("750");
    assert.equal(await admin.evaluate((id) => workflow.nodes.find((node) => node.id === id).params.delay_ms, delayId), 750);
    await admin.locator("#inspectorClose").click();
    const before = await admin.evaluate(() => ({ ...workflow.nodes.find((node) => node.id === "play").position }));
    await admin.locator('[data-node-id="play"]').dragTo(admin.locator("#canvasViewport"), {
      sourcePosition: { x: 20, y: 20 }, targetPosition: { x: 740, y: 270 },
    });
    const after = await admin.evaluate(() => workflow.nodes.find((node) => node.id === "play").position);
    assert.notDeepEqual(after, before);
    await admin.locator('[data-node-id="play"]').click();
    await admin.locator("#workflowInspector").waitFor({ state: "visible" });
    await admin.locator("#inspectorClose").click();
    await admin.locator("#linkMode").click();
    await admin.locator("#edgeWhenWrap").waitFor({ state: "visible" });
    await admin.locator('[data-node-id="play"]').click();
    await admin.locator('[data-node-id="end"]').click();
    await admin.locator("#edgeWhenWrap").waitFor({ state: "hidden" });
    assert.ok(await admin.evaluate(() => workflow.edges.some((edge) => edge.source === "play" && edge.target === "end")));
    const content = await admin.evaluate(() => window.UsageFlow.fingerprint(workflow));
    await admin.locator("#zoomOut").click();
    await admin.locator("#workflowsTab").click();
    await admin.locator("#nodesTab").click();
    assert.equal(await admin.evaluate(() => window.UsageFlow.fingerprint(workflow)), content);
    assert.equal(await admin.locator("#unsavedDialog").isVisible(), false);
    await admin.screenshot({ path: path.join(output, "nodes.png"), fullPage: true });
    await admin.locator("#workflowsTab").click();
    await admin.locator('[data-workflow-id="' + b + '"]').click();
    await choose("discard");
    await until(() => admin.evaluate((id) => workflow?.id === id && !document.querySelector(".workflow-toolbar").inert, b), "discard not completed");
    await selectWorkflow(a);
  });
  await check("offline simulation and collapsed run details remain usable across refreshes", async () => {
    await admin.locator("#dryRunWorkflow").click();
    await until(async () => (await admin.locator("#validationMessage").textContent()).includes("模拟成功"), "offline simulation failed");
    assert.equal(await admin.locator("#workflowRuns").getAttribute("open"), null);
    await admin.locator("#workflowRuns > summary").click();
    const runs = await api("/api/workflow-runs?limit=30");
    const ownRun = runs.runs.find((run) => run.workflow_id === a && run.mode === "dry_run");
    assert.ok(ownRun);
    const entry = admin.locator('[data-run-id="' + ownRun.run_id + '"]');
    await entry.getByRole("button", { name: "步骤" }).click();
    await entry.locator(".run-steps").waitFor({ state: "visible" });
    await admin.waitForTimeout(3200);
    assert.equal(await entry.locator(".run-steps").isVisible(), true);
    await admin.screenshot({ path: path.join(output, "runs.png"), fullPage: true });
    await admin.locator("#workflowRuns > summary").click();
  });
  await check("removed runtime panels do not leave status polling on the page manager", async () => {
    await admin.locator('.workflow-primary-nav a[href="/display-pages"]').click();
    const polls = [];
    const capture = (request) => { if (/\/api\/(?:status|workflow-status)(?:\?|$)/.test(request.url())) polls.push(request.url()); };
    admin.on("request", capture);
    await admin.waitForTimeout(1700);
    admin.off("request", capture);
    assert.equal(await admin.locator(".usage-status, .usage-readiness").count(), 0);
    assert.deepEqual(polls, []);
    await admin.screenshot({ path: path.join(output, "pages.png"), fullPage: true });
    await admin.locator('.settings-header-tools a[href="/settings"]').click();
    assert.equal(await admin.locator(".usage-status").count(), 0);
    await admin.screenshot({ path: path.join(output, "settings.png"), fullPage: true });
    await admin.locator('.settings-header-tools a[href="/workflows"]').click();
  });
  await selectWorkflow(a);
  await admin.locator("#workflowName").fill("宣传片播放控制");
  await admin.locator("#saveWorkflow").click();
  await until(() => admin.evaluate(() => !savePromise && !draftState.dirty(workflow, workflowIsDraft)), "final sample not saved");
  await admin.screenshot({ path: path.join(output, "workflows.png"), fullPage: true });
  await check("desktop layout keeps runtime feedback and run records visible at 1366 by 768", async () => {
    await admin.setViewportSize({ width: 1366, height: 768 });
    const bounds = await admin.evaluate(() => ({
      runsBottom: document.querySelector(".workflow-runs").getBoundingClientRect().bottom,
      height: innerHeight,
      canvasTop: document.querySelector(".workflow-canvas").getBoundingClientRect().top,
      triggerBottom: document.querySelector(".trigger-editor").getBoundingClientRect().bottom,
    }));
    assert.ok(bounds.runsBottom <= bounds.height + 1, JSON.stringify(bounds));
    assert.ok(bounds.canvasTop >= bounds.triggerBottom, JSON.stringify(bounds));
    assert.ok(bounds.canvasTop <= 225, JSON.stringify(bounds));
    await admin.screenshot({ path: path.join(output, "workflows-1366.png"), fullPage: true });
    await admin.setViewportSize({ width: 1920, height: 1080 });
    await admin.screenshot({ path: path.join(output, "workflows-1920.png"), fullPage: true });
    assert.equal(await admin.locator("#workflowRuns").getAttribute("open"), null);
  });
  const managementBox = await display.locator("#openManagement").boundingBox();
  const fullscreenBox = await display.frameLocator("#displayPageFrame").locator("#fullscreenButton").boundingBox();
  assert.ok(managementBox.x > 1000, "management entry must be aligned to the right");
  assert.ok(managementBox.x + managementBox.width <= fullscreenBox.x - 4, "management entry must not overlap fullscreen");
  assert.ok(Math.abs(managementBox.y - fullscreenBox.y) <= 10, "display controls must share a top edge");
  await display.screenshot({ path: path.join(output, "display.png"), fullPage: true });
  assert.deepEqual(versionRequests, [], "frontend must not request removed version controls");
  assert.deepEqual(errors, [], "browser JavaScript errors");
  fs.writeFileSync(path.join(output, "report.json"), JSON.stringify({ passed: results, errors }, null, 2));
})().catch(async (error) => {
  console.error(error);
  if (admin) await admin.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
  process.exitCode = 1;
}).finally(async () => {
  if (context) {
    await context.request.post(base + "/api/pointer/mode", { data: { enabled: false } }).catch(() => {});
    for (const id of ids) {
      await context.request.post(base + "/api/workflows/" + id + "/disable").catch(() => {});
      await context.request.delete(base + "/api/workflows/" + id).catch(() => {});
    }
  }
  if (browser) await browser.close();
});
