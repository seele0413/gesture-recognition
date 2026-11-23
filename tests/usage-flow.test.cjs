const test = require("node:test");
const assert = require("node:assert/strict");
const flow = require("../web/usage-flow.js");

const definition = () => ({
  id: "one", name: "视频播放", description: "", enabled: false, version: 1,
  trigger: { type: "gesture_trigger", gesture: "Open_Palm", page_scope: "promo" },
  nodes: [{ id: "play", type: "action", action: "video.play", params: {}, position: { x: 170, y: 80 } }],
  edges: [],
});

test("lock feedback reads actual frame settings and distinguishes confirmed SUSPECT", () => {
  assert.match(flow.lockPrompt({ lock_progress: 1, lock_required_frames: 2, lock_window_frames: 5 }), /1\/2（最近 5 帧）/);
  assert.match(flow.lockPrompt({ lock_progress: 2, lock_required_frames: 4, lock_window_frames: 7 }), /2\/4（最近 7 帧）/);
  assert.equal(flow.controllerView({ state: "suspect", identity_confirmed: true }).kind, "ready");
  assert.match(flow.controllerView({ state: "suspect", identity_confirmed: false }).label, /暂停/);
  assert.equal(flow.controllerView({ state: "suspect" }).kind, "waiting");
  assert.equal(flow.controllerView({ state: "reacquiring", identity_confirmed: true }).kind, "waiting");
});

test("draft comparison detects metadata, trigger, parameter, edge and layout changes", () => {
  const state = new flow.DraftState();
  const original = definition();
  state.saved(original);
  for (const change of [
    (d) => { d.name = "改名"; }, (d) => { d.trigger.page_scope = "factory"; },
    (d) => { d.nodes[0].params.enabled = false; }, (d) => { d.nodes[0].position.x++; },
    (d) => { d.edges.push({ source: "play", target: "end" }); },
  ]) {
    const modified = structuredClone(original);
    change(modified);
    assert.equal(state.dirty(modified), true);
  }
  assert.equal(state.dirty({ ...original, enabled: true, version: 4, updated_at: "later" }), false);
  assert.equal(state.dirty(original, true), true);
  assert.equal(state.dirty(null), false);
});

test("save failure or cancellation preserves the dirty editor; successful save may proceed", async () => {
  const state = new flow.DraftState();
  const draft = definition();
  state.saved(draft);
  draft.name = "未保存";
  let saves = 0;
  assert.equal(await state.canLeave(draft, false, async () => "cancel", async () => saves++), false);
  assert.equal(saves, 0);
  await assert.rejects(state.canLeave(draft, false, async () => "save", async () => { throw new Error("保存失败"); }), /保存失败/);
  assert.equal(state.dirty(draft), true);
  assert.equal(await state.canLeave(draft, false, async () => "save", async () => { saves++; state.saved(draft); }), true);
  assert.equal(state.dirty(draft), false);
  draft.name = "再次修改";
  assert.equal(await state.canLeave(draft, false, async () => "discard", async () => saves++), true);
  assert.equal(saves, 1);
});

test("focusing an existing management window preserves its subpage and unsaved editor", () => {
  const calls = [];
  const existing = {
    location: { href: "http://localhost/workflows", replace: () => assert.fail("must not navigate an existing window") },
    focus: () => calls.push("focus"),
  };
  const host = { open: (url, name) => { calls.push([url, name]); return existing; } };
  assert.equal(flow.openWindow("admin", "/settings", host), existing);
  assert.deepEqual(calls, [["", flow.WINDOW_NAMES.admin], "focus"]);
});

test("opening a first display navigates once, and popup rejection is actionable", () => {
  const calls = [];
  const host = { open: () => ({
    location: { href: "about:blank", replace: (path) => calls.push(path) }, focus() {},
  }) };
  flow.openWindow("display", "/", host);
  assert.deepEqual(calls, ["/"]);
  assert.throws(() => flow.openWindow("admin", "/settings", { open: () => null }), /允许.*弹出窗口/);
  assert.throws(() => flow.openWindow("admin", "https://example.com", host), /未登记/);
});
