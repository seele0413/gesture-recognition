const test = require("node:test");
const assert = require("node:assert/strict");
const Graph = require("../web/workflow-graph.js");

function action(id, onError = "stop", x = 170) {
  return { id, type: "action", action: "video.play", params: {}, timeout_ms: 3000, on_error: onError, retries: 0, position: { x, y: 180 } };
}
function delay(id, x = 470) {
  return { id, type: "delay", params: { delay_ms: 500 }, position: { x, y: 180 } };
}
function end(id, x = 770, y = 180) {
  return { id, type: "end", params: {}, position: { x, y } };
}
function chain() {
  return {
    nodes: [action("play", "stop", 170), delay("wait", 470), end("end", 770)],
    edges: [{ source: "play", target: "wait" }, { source: "wait", target: "end" }],
  };
}
function edge(workflow, source, target, when) {
  return workflow.edges.find((item) => item.source === source && item.target === target && (item.when ?? undefined) === when);
}

test("default insertion resolves the only terminal edge", () => {
  const workflow = chain();
  const result = Graph.resolveInsertEdge(workflow);
  assert.equal(result.ok, true);
  assert.equal(result.edge.source, "wait");
  assert.equal(result.edge.target, "end");
});

test("selecting a node inserts after that node, while selecting an end inserts before it", () => {
  const workflow = chain();
  assert.equal(Graph.resolveInsertEdge(workflow, { selectedNodeId: "play" }).edge.target, "wait");
  assert.equal(Graph.resolveInsertEdge(workflow, { selectedNodeId: "end" }).edge.source, "wait");
});

test("ambiguous branch tails require explicit edge selection", () => {
  const workflow = {
    nodes: [
      { id: "gate", type: "condition", params: { field: "confidence", operator: "gte", value: 0.5 } },
      end("yes", 470, 100), end("no", 470, 280),
    ],
    edges: [
      { source: "gate", target: "yes", when: "true" },
      { source: "gate", target: "no", when: "false" },
    ],
  };
  const result = Graph.resolveInsertEdge(workflow);
  assert.equal(result.ok, false);
  assert.equal(result.reason, "multiple-terminal-paths");
  assert.equal(result.candidates.length, 2);
  assert.equal(Graph.resolveInsertEdge(workflow, { selectedEdgeKey: Graph.edgeKey(edge(workflow, "gate", "yes", "true")) }).ok, true);
});

test("inserting a normal node splits the edge and shifts downstream nodes to prevent overlap", () => {
  const workflow = chain();
  const targetEdge = edge(workflow, "wait", "end", undefined);
  const result = Graph.insertNodeAtEdge(workflow, action("mute"), targetEdge);
  assert.equal(result.ok, true);
  assert.ok(edge({ edges: result.edges }, "wait", "mute", undefined));
  assert.ok(edge({ edges: result.edges }, "mute", "end", undefined));
  assert.equal(result.nodes.find((node) => node.id === "mute").position.x, 770);
  assert.equal(result.nodes.find((node) => node.id === "end").position.x, 1070);
  assert.deepEqual(Graph.validateGraphStructure({ nodes: result.nodes, edges: result.edges }), []);
});

test("inserting into true, false and error branches preserves the original branch label", () => {
  const cases = ["true", "false", "error"];
  for (const label of cases) {
    const source = label === "error" ? action("source", "branch") : { id: "source", type: "condition", params: { field: "confidence", operator: "gte", value: 0.5 }, position: { x: 170, y: 180 } };
    const target = end("target", 470, 180);
    const other = label === "true" ? end("other", 470, 350) : null;
    const nodes = [source, target];
    const edges = [{ source: "source", target: "target", when: label }];
    if (label === "true") { nodes.push(other); edges.push({ source: "source", target: "other", when: "false" }); }
    if (label === "false") { nodes.push(other = end("other", 470, 350)); edges.push({ source: "source", target: "other", when: "true" }); }
    if (label === "error") { nodes.push(end("normal", 470, 350)); edges.push({ source: "source", target: "normal" }); }
    const workflow = { nodes, edges };
    const result = Graph.insertNodeAtEdge(workflow, delay("inserted"), edge(workflow, "source", "target", label));
    assert.equal(result.ok, true);
    assert.ok(edge({ edges: result.edges }, "source", "inserted", label));
    assert.ok(edge({ edges: result.edges }, "inserted", "target", undefined));
    assert.deepEqual(Graph.validateGraphStructure({ nodes: result.nodes, edges: result.edges }), []);
  }
});

test("the trigger edge can be used to insert a new root node", () => {
  const workflow = { nodes: [end("end", 170)], edges: [] };
  const virtual = Graph.getVirtualRootEdge(workflow);
  const result = Graph.insertNodeAtEdge(workflow, action("start"), virtual);
  assert.equal(result.ok, true);
  assert.ok(edge({ edges: result.edges }, "start", "end", undefined));
  assert.equal(Graph.getRootNode({ nodes: result.nodes, edges: result.edges }).id, "start");
  assert.deepEqual(Graph.validateGraphStructure({ nodes: result.nodes, edges: result.edges }), []);
});

test("inserting a condition continues the original flow on true and creates a false end", () => {
  const workflow = chain();
  const result = Graph.insertNodeAtEdge(workflow, {
    id: "condition",
    type: "condition",
    params: { field: "confidence", operator: "gte", value: 0.7 },
  }, edge(workflow, "wait", "end", undefined), { idFactory: (prefix) => prefix + "-generated" });
  assert.equal(result.ok, true);
  assert.ok(edge({ edges: result.edges }, "condition", "end", "true"));
  assert.ok(edge({ edges: result.edges }, "condition", "end-false-generated", "false"));
  assert.deepEqual(Graph.validateGraphStructure({ nodes: result.nodes, edges: result.edges }), []);
});

test("deleting a linear middle node reconnects its predecessor and successor", () => {
  const workflow = {
    nodes: [
      { id: "gate", type: "condition", params: { field: "confidence", operator: "gte", value: 0.5 } },
      delay("middle", 470), end("yes", 770, 100), end("no", 470, 300),
    ],
    edges: [
      { source: "gate", target: "middle", when: "true" },
      { source: "gate", target: "no", when: "false" },
      { source: "middle", target: "yes" },
    ],
  };
  const result = Graph.removeNode(workflow, "middle");
  assert.equal(result.ok, true);
  assert.ok(edge({ edges: result.edges }, "gate", "yes", "true"));
  assert.ok(edge({ edges: result.edges }, "gate", "no", "false"));
  assert.deepEqual(Graph.validateGraphStructure({ nodes: result.nodes, edges: result.edges }), []);
});

test("deleting the root linear node promotes its successor to the new root", () => {
  const workflow = chain();
  const result = Graph.removeNode(workflow, "play");
  assert.equal(result.ok, true);
  assert.equal(Graph.getRootNode({ nodes: result.nodes, edges: result.edges }).id, "wait");
  assert.deepEqual(Graph.validateGraphStructure({ nodes: result.nodes, edges: result.edges }), []);
});

test("branch nodes and end nodes cannot be deleted through an unsafe linear delete", () => {
  const workflow = {
    nodes: [
      { id: "gate", type: "condition", params: { field: "confidence", operator: "gte", value: 0.5 } },
      end("yes", 470, 100), end("no", 470, 280),
    ],
    edges: [
      { source: "gate", target: "yes", when: "true" },
      { source: "gate", target: "no", when: "false" },
    ],
  };
  assert.equal(Graph.removeNode(workflow, "gate").ok, false);
  assert.equal(Graph.removeNode(workflow, "yes").ok, false);
});

test("connections reject occupied outputs, invalid branch labels and cycles", () => {
  const workflow = chain();
  assert.match(Graph.connectNodes(workflow, "play", "end", undefined).error, /已经有连接/);
  assert.match(Graph.connectNodes(workflow, "play", "end", "true").error, /不支持/);
  const disconnected = Graph.removeEdge(workflow, Graph.edgeKey(edge(workflow, "wait", "end", undefined)));
  const cycle = Graph.connectNodes(disconnected, "wait", "play", undefined);
  assert.match(cycle.error, /循环/);
});

test("condition and error-branch output slots accept only their declared labels", () => {
  const workflow = {
    nodes: [
      { id: "gate", type: "condition", params: { field: "confidence", operator: "gte", value: 0.5 } },
      end("yes"), end("no", 470, 300),
    ],
    edges: [
      { source: "gate", target: "yes", when: "true" },
      { source: "gate", target: "no", when: "false" },
    ],
  };
  assert.match(Graph.connectNodes(workflow, "gate", "yes", undefined).error, /不支持/);
});

test("switching an action to error-branch mode creates a safe error end and can revert it", () => {
  const workflow = { nodes: [action("play"), end("end", 470)], edges: [{ source: "play", target: "end" }] };
  const enabled = Graph.setActionErrorPolicy(workflow, "play", "branch", { idFactory: (prefix) => prefix + "-auto" });
  assert.equal(enabled.ok, true);
  assert.ok(edge({ edges: enabled.edges }, "play", "end-error-auto", "error"));
  assert.deepEqual(Graph.validateGraphStructure({ nodes: enabled.nodes, edges: enabled.edges }), []);
  const disabled = Graph.setActionErrorPolicy({ nodes: enabled.nodes, edges: enabled.edges }, "play", "stop");
  assert.equal(disabled.ok, true);
  assert.equal(disabled.nodes.some((node) => node.id === "end-error-auto"), false);
  assert.deepEqual(Graph.validateGraphStructure({ nodes: disabled.nodes, edges: disabled.edges }), []);
});

test("an action error branch with real downstream work cannot be silently discarded", () => {
  const workflow = {
    nodes: [action("play", "branch"), delay("recover", 470), end("normal", 770), end("error", 770, 360)],
    edges: [
      { source: "play", target: "normal" },
      { source: "play", target: "recover", when: "error" },
      { source: "recover", target: "error" },
    ],
  };
  const result = Graph.setActionErrorPolicy(workflow, "play", "stop");
  assert.equal(result.ok, false);
  assert.match(result.error, /先处理/);
});

test("history restores graph edits and supports redo", () => {
  const workflow = chain();
  const history = Graph.createHistory(10);
  const before = Graph.snapshot(workflow);
  history.pushSnapshot(before);
  workflow.nodes.push(action("new"));
  const undone = history.undo(workflow);
  assert.deepEqual(undone.nodes.map((node) => node.id), ["play", "wait", "end"]);
  Graph.restore(workflow, undone);
  const redone = history.redo(workflow);
  assert.deepEqual(redone.nodes.map((node) => node.id), ["play", "wait", "end", "new"]);
});

test("structural validator detects cycles, unreachable nodes and incomplete branches", () => {
  const workflow = chain();
  workflow.edges.push({ source: "end", target: "play" });
  assert.ok(Graph.validateGraphStructure(workflow).some((message) => message.includes("循环")));
  const incomplete = {
    nodes: [{ id: "gate", type: "condition", params: {} }, end("yes")],
    edges: [{ source: "gate", target: "yes", when: "true" }],
  };
  assert.ok(Graph.validateGraphStructure(incomplete).some((message) => message.includes("true 和 false")));
});
