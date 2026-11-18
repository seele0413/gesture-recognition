const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");

test("browser UMD export exposes a constructible PointerEventBuffer class", () => {
  const source = fs.readFileSync(path.join(root, "web/pointer-event-buffer.js"), "utf8");
  const browserGlobal = {};
  vm.runInNewContext(source, browserGlobal);

  assert.equal(typeof browserGlobal.PointerEventBuffer, "object");
  assert.equal(typeof browserGlobal.PointerEventBuffer.PointerEventBuffer, "function");
  const buffer = new browserGlobal.PointerEventBuffer.PointerEventBuffer();
  assert.equal(typeof buffer.push, "function");
  assert.equal(typeof buffer.drain, "function");
});

test("workflow editor consumes the class from the UMD namespace, not the namespace itself", () => {
  const source = fs.readFileSync(path.join(root, "web/workflows.js"), "utf8");
  assert.match(source, /window\.PointerEventBuffer\?\.PointerEventBuffer/);
  assert.match(source, /new PointerEventBufferClass\(\)/);
  assert.doesNotMatch(source, /new PointerEventBuffer\(\)/);
});

test("workflow editor keeps camera-pointer module failure separate from mouse editing", () => {
  const source = fs.readFileSync(path.join(root, "web/workflows.js"), "utf8");
  assert.match(source, /const pointerEventBuffer = typeof PointerEventBufferClass === "function"/);
  assert.match(source, /if \(!pointerEventBuffer \|\| !window\.PointerGeometry\)/);
  assert.match(source, /鼠标和键盘编辑仍然可用/);
});
