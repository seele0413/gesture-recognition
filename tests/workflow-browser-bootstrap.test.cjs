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

test("gesture mappings are presented inside workflows instead of the settings page", () => {
  const settings = fs.readFileSync(path.join(root, "web/settings.html"), "utf8");
  const workflows = fs.readFileSync(path.join(root, "web/workflows.html"), "utf8");
  const script = fs.readFileSync(path.join(root, "web/workflows.js"), "utf8");
  assert.doesNotMatch(settings, /mappingGrid|mappingHeading|saveMappings/);
  assert.match(workflows, /id="gestureWorkflowMap"/);
  assert.match(workflows, /要用多个手势控制同一个网页/);
  assert.match(script, /function renderGestureWorkflowMap\(\)/);
});

test("AI workflow dialog configures relay providers and tests API compatibility without exposing secrets", () => {
  const workflows = fs.readFileSync(path.join(root, "web/workflows.html"), "utf8");
  const script = fs.readFileSync(path.join(root, "web/workflows.js"), "utf8");
  const backend = fs.readFileSync(path.join(root, "app/main.py"), "utf8");
  const generator = fs.readFileSync(path.join(root, "app/workflow_generator.py"), "utf8");
  assert.match(workflows, /id="workflowGeneratorApiKey" type="password"/);
  assert.match(workflows, /id="workflowGeneratorBaseUrl"/);
  assert.match(workflows, /id="workflowGeneratorModel"/);
  assert.match(workflows, /id="workflowGeneratorProtocol"/);
  assert.match(workflows, /id="testWorkflowGeneratorConnection"/);
  assert.match(script, /\/api\/workflow-generator\/config/);
  assert.match(script, /\/api\/workflow-generator\/test/);
  assert.match(backend, /@app\.put\("\/api\/workflow-generator\/config"\)/);
  assert.match(backend, /@app\.post\("\/api\/workflow-generator\/test"\)/);
  assert.match(generator, /def _request_chat_completions/);
  assert.match(generator, /def _request_compatible/);
});
