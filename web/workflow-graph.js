(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WorkflowGraph = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  let generatedId = 0;

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function snapshot(workflow) {
    return {
      nodes: clone(workflow && Array.isArray(workflow.nodes) ? workflow.nodes : []),
      edges: clone(workflow && Array.isArray(workflow.edges) ? workflow.edges : []),
      trigger: clone(workflow && workflow.trigger ? workflow.trigger : {}),
    };
  }

  function restore(workflow, state) {
    workflow.nodes = clone(state.nodes || []);
    workflow.edges = clone(state.edges || []);
    workflow.trigger = clone(state.trigger || {});
    return workflow;
  }

  function normalizeWhen(when) {
    return when === null || when === "" ? undefined : when;
  }

  function edgeKey(edge) {
    return JSON.stringify([edge.source, edge.target, normalizeWhen(edge.when) ?? null]);
  }

  function copyEdge(edge) {
    const result = { source: edge.source, target: edge.target };
    const when = normalizeWhen(edge.when);
    if (when !== undefined) result.when = when;
    return result;
  }

  function buildIndex(workflow) {
    const nodes = new Map((workflow.nodes || []).map((node) => [node.id, node]));
    const incoming = new Map();
    const outgoing = new Map();
    for (const node of nodes.values()) {
      incoming.set(node.id, []);
      outgoing.set(node.id, []);
    }
    for (const edge of workflow.edges || []) {
      if (incoming.has(edge.target)) incoming.get(edge.target).push(edge);
      if (outgoing.has(edge.source)) outgoing.get(edge.source).push(edge);
    }
    return { nodes, incoming, outgoing };
  }

  function getRootNode(workflow, index = buildIndex(workflow)) {
    return (workflow.nodes || []).find((node) => (index.incoming.get(node.id) || []).length === 0) || null;
  }

  function getVirtualRootEdge(workflow) {
    const index = buildIndex(workflow);
    const root = getRootNode(workflow, index);
    if (!root) return null;
    return { source: "trigger", target: root.id, virtual: true };
  }

  function findEdge(workflow, key) {
    return (workflow.edges || []).find((edge) => edgeKey(edge) === key) || null;
  }

  function resolveInsertEdge(workflow, options = {}) {
    const index = buildIndex(workflow);
    const selectedEdgeKey = options.selectedEdgeKey || null;
    if (selectedEdgeKey) {
      const edge = findEdge(workflow, selectedEdgeKey);
      if (edge) return { ok: true, edge, reason: "selected-edge" };
      const virtual = getVirtualRootEdge(workflow);
      if (virtual && edgeKey(virtual) === selectedEdgeKey) return { ok: true, edge: virtual, reason: "selected-root-edge" };
      return { ok: false, reason: "selected-edge-missing", candidates: [] };
    }

    const selectedNodeId = options.selectedNodeId || null;
    if (selectedNodeId) {
      const node = index.nodes.get(selectedNodeId);
      if (!node) return { ok: false, reason: "selected-node-missing", candidates: [] };
      if (node.type === "end") {
        const incoming = index.incoming.get(node.id) || [];
        if (incoming.length === 1) return { ok: true, edge: incoming[0], reason: "before-selected-end" };
        if (incoming.length === 0 && getRootNode(workflow, index)?.id === node.id) {
          const virtual = getVirtualRootEdge(workflow);
          return virtual ? { ok: true, edge: virtual, reason: "empty-workflow" } : { ok: false, reason: "no-insert-target", candidates: [] };
        }
        return { ok: false, reason: "end-has-multiple-incoming", candidates: incoming };
      }
      const outgoing = index.outgoing.get(node.id) || [];
      if (outgoing.length === 1) return { ok: true, edge: outgoing[0], reason: "after-selected-node" };
      if (outgoing.length > 1) return { ok: false, reason: "selected-node-has-branches", candidates: outgoing };
      return { ok: false, reason: "selected-node-has-no-output", candidates: [] };
    }

    const root = getRootNode(workflow, index);
    if (root && root.type === "end" && (workflow.edges || []).length === 0) {
      const virtual = getVirtualRootEdge(workflow);
      return { ok: true, edge: virtual, reason: "empty-workflow" };
    }

    const terminalEdges = (workflow.edges || []).filter((edge) => index.nodes.get(edge.target)?.type === "end");
    if (terminalEdges.length === 1) return { ok: true, edge: terminalEdges[0], reason: "single-terminal-path" };
    if (terminalEdges.length > 1) return { ok: false, reason: "multiple-terminal-paths", candidates: terminalEdges };
    return { ok: false, reason: "no-insert-target", candidates: [] };
  }

  function makeId(prefix, options, existingIds) {
    let id = null;
    if (typeof options.idFactory === "function") id = options.idFactory(prefix);
    if (!id && typeof globalThis !== "undefined" && globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
      id = prefix + "-" + globalThis.crypto.randomUUID().slice(0, 8);
    }
    if (!id) {
      generatedId += 1;
      id = prefix + "-auto-" + generatedId;
    }
    while (existingIds.has(id)) {
      generatedId += 1;
      id = prefix + "-auto-" + generatedId;
    }
    return id;
  }

  function shiftDownstream(nodes, edges, startId, amount) {
    if (!amount || amount <= 0) return;
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const outgoing = new Map();
    for (const edge of edges) {
      if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
      outgoing.get(edge.source).push(edge.target);
    }
    const queue = [startId];
    const visited = new Set();
    while (queue.length) {
      const id = queue.shift();
      if (visited.has(id)) continue;
      visited.add(id);
      const node = byId.get(id);
      if (node) {
        if (!node.position) node.position = { x: 170, y: 180 };
        node.position = { x: node.position.x + amount, y: node.position.y };
      }
      for (const target of outgoing.get(id) || []) queue.push(target);
    }
  }

  function insertNodeAtEdge(workflow, node, edge, options = {}) {
    if (!edge || !edge.source || !edge.target) return { ok: false, error: "插入位置无效" };
    if (!node || !node.id || !node.type) return { ok: false, error: "新节点定义无效" };
    if (node.type === "end") return { ok: false, error: "结束节点是路径终点，不能插入到已有连线中" };

    const currentIndex = buildIndex(workflow);
    if (currentIndex.nodes.has(node.id)) return { ok: false, error: "节点 ID 已存在" };
    const target = currentIndex.nodes.get(edge.target);
    if (!target) return { ok: false, error: "连线目标节点不存在" };

    const isVirtual = edge.virtual === true || edge.source === "trigger";
    let originalEdge = null;
    if (isVirtual) {
      const root = getRootNode(workflow, currentIndex);
      if (!root || root.id !== edge.target) return { ok: false, error: "触发器入口已发生变化，请重新选择连线" };
    } else {
      originalEdge = findEdge(workflow, edgeKey(edge));
      if (!originalEdge) return { ok: false, error: "所选连线已不存在，请重新选择" };
    }

    const nodes = clone(workflow.nodes || []);
    const edges = clone(workflow.edges || []);
    const sourceNode = isVirtual ? null : currentIndex.nodes.get(edge.source);
    if (!isVirtual && !sourceNode) return { ok: false, error: "连线起点节点不存在" };

    const targetPosition = target.position || { x: 470, y: 180 };
    const nodeX = sourceNode ? (sourceNode.position?.x ?? 170) + 300 : 170;
    const nodeY = Number.isFinite(options.position?.y) ? Math.max(20, Math.round(options.position.y)) : targetPosition.y;
    const shift = Math.max(0, nodeX + 300 - targetPosition.x);
    shiftDownstream(nodes, edges, edge.target, shift);

    const nodeCopy = clone(node);
    nodeCopy.position = { x: nodeX, y: nodeY };
    if (!Array.isArray(nodeCopy.params)) nodeCopy.params = nodeCopy.params || {};

    if (!isVirtual) {
      const index = edges.findIndex((item) => edgeKey(item) === edgeKey(originalEdge));
      if (index < 0) return { ok: false, error: "所选连线已发生变化，请重新选择" };
      edges.splice(index, 1);
      edges.push(copyEdge({ source: edge.source, target: nodeCopy.id, when: edge.when }));
    }

    nodes.push(nodeCopy);
    if (nodeCopy.type === "condition") {
      const existingIds = new Set(nodes.map((item) => item.id));
      const falseEnd = {
        id: makeId("end-false", options, existingIds),
        type: "end",
        params: {},
        position: { x: nodeX + 300, y: nodeY + 180 },
      };
      nodes.push(falseEnd);
      edges.push({ source: nodeCopy.id, target: edge.target, when: "true" });
      edges.push({ source: nodeCopy.id, target: falseEnd.id, when: "false" });
      return { ok: true, nodes, edges, selectedNodeId: nodeCopy.id, createdNodeIds: [nodeCopy.id, falseEnd.id] };
    }

    edges.push({ source: nodeCopy.id, target: edge.target });
    return { ok: true, nodes, edges, selectedNodeId: nodeCopy.id, createdNodeIds: [nodeCopy.id] };
  }

  function allowedOutputWhen(node, when) {
    const normalized = normalizeWhen(when);
    if (node.type === "condition") return normalized === "true" || normalized === "false";
    if (node.type === "action" && node.on_error === "branch") return normalized === undefined || normalized === "error";
    return normalized === undefined;
  }

  function addEndNode(workflow, node, sourceId, when, options = {}) {
    if (!node || node.type !== "end") return { ok: false, error: "只能添加结束节点" };
    const index = buildIndex(workflow);
    const source = index.nodes.get(sourceId);
    if (!source || source.type === "end") return { ok: false, error: "请先选择一个可以创建出口的节点" };
    if (!allowedOutputWhen(source, when)) return { ok: false, error: "所选连线类型不适用于该节点" };
    const outgoing = index.outgoing.get(sourceId) || [];
    if (outgoing.some((edge) => normalizeWhen(edge.when) === normalizeWhen(when))) {
      return { ok: false, error: "该出口已经连接，请先选择对应连线进行编辑" };
    }
    const existingIds = new Set(index.nodes.keys());
    if (!node.id || existingIds.has(node.id)) return { ok: false, error: "节点 ID 已存在或无效" };
    const nodes = clone(workflow.nodes || []);
    const edges = clone(workflow.edges || []);
    const sourceCopy = nodes.find((item) => item.id === sourceId);
    const position = sourceCopy.position || { x: 170, y: 180 };
    const endNode = clone(node);
    endNode.position = { x: position.x + 300, y: position.y + (normalizeWhen(when) === "error" ? 150 : 0) };
    nodes.push(endNode);
    edges.push(copyEdge({ source: sourceId, target: endNode.id, when }));
    return { ok: true, nodes, edges, selectedNodeId: endNode.id, createdNodeIds: [endNode.id] };
  }

  function isReachable(workflow, startId, targetId) {
    if (startId === targetId) return true;
    const outgoing = new Map();
    for (const edge of workflow.edges || []) {
      if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
      outgoing.get(edge.source).push(edge.target);
    }
    const queue = [startId];
    const visited = new Set();
    while (queue.length) {
      const current = queue.shift();
      if (visited.has(current)) continue;
      visited.add(current);
      for (const next of outgoing.get(current) || []) {
        if (next === targetId) return true;
        queue.push(next);
      }
    }
    return false;
  }

  function connectNodes(workflow, sourceId, targetId, when) {
    const index = buildIndex(workflow);
    const source = index.nodes.get(sourceId);
    const target = index.nodes.get(targetId);
    const normalized = normalizeWhen(when);
    if (!source || !target) return { ok: false, error: "连接的节点不存在" };
    if (source.type === "end") return { ok: false, error: "结束节点不能作为连线起点" };
    if (sourceId === targetId) return { ok: false, error: "节点不能连接到自身" };
    if (!allowedOutputWhen(source, normalized)) return { ok: false, error: "该节点不支持所选出口类型" };
    const outgoing = index.outgoing.get(sourceId) || [];
    if (outgoing.some((edge) => normalizeWhen(edge.when) === normalized)) {
      return { ok: false, error: "该出口已经有连接；请先选中原连线并断开，再重新连接" };
    }
    if (isReachable(workflow, targetId, sourceId)) return { ok: false, error: "该连接会形成循环，已阻止" };
    const nodes = clone(workflow.nodes || []);
    const edges = clone(workflow.edges || []);
    const nextEdge = { source: sourceId, target: targetId };
    if (normalized !== undefined) nextEdge.when = normalized;
    edges.push(nextEdge);
    return { ok: true, nodes, edges, selectedNodeId: targetId };
  }

  function removeEdge(workflow, key) {
    const edge = findEdge(workflow, key);
    if (!edge) return { ok: false, error: "所选连线不存在或不能删除" };
    return {
      ok: true,
      nodes: clone(workflow.nodes || []),
      edges: clone(workflow.edges || []).filter((item) => edgeKey(item) !== key),
      selectedNodeId: null,
    };
  }

  function canDeleteNode(workflow, nodeId) {
    const index = buildIndex(workflow);
    const node = index.nodes.get(nodeId);
    if (!node) return { ok: false, reason: "节点不存在" };
    if (node.type === "end") return { ok: false, reason: "结束节点不能单独删除" };
    const outgoing = index.outgoing.get(nodeId) || [];
    if (outgoing.length !== 1) return { ok: false, reason: "该节点有多个出口或没有后继，不能自动合并；请先处理分支" };
    return { ok: true, reason: "" };
  }

  function removeNode(workflow, nodeId) {
    const capability = canDeleteNode(workflow, nodeId);
    if (!capability.ok) return { ok: false, error: capability.reason };
    const index = buildIndex(workflow);
    const outgoing = index.outgoing.get(nodeId) || [];
    const incoming = index.incoming.get(nodeId) || [];
    const nextTarget = outgoing[0].target;
    const nodes = clone(workflow.nodes || []).filter((node) => node.id !== nodeId);
    let edges = clone(workflow.edges || []).filter((edge) => edge.source !== nodeId && edge.target !== nodeId);
    for (const edge of incoming) {
      const replacement = copyEdge({ source: edge.source, target: nextTarget, when: edge.when });
      if (!edges.some((item) => edgeKey(item) === edgeKey(replacement))) edges.push(replacement);
    }
    return { ok: true, nodes, edges, selectedNodeId: null };
  }

  function canDuplicateNode(workflow, nodeId) {
    const index = buildIndex(workflow);
    const node = index.nodes.get(nodeId);
    if (!node || !["action", "delay", "wait_event"].includes(node.type)) return { ok: false, reason: "该类型节点不能复制" };
    const outgoing = index.outgoing.get(nodeId) || [];
    if (outgoing.length !== 1) return { ok: false, reason: "只有一条执行出口的节点才能直接复制" };
    return { ok: true, reason: "" };
  }

  function duplicateNode(workflow, nodeId, options = {}) {
    const capability = canDuplicateNode(workflow, nodeId);
    if (!capability.ok) return { ok: false, error: capability.reason };
    const index = buildIndex(workflow);
    const node = index.nodes.get(nodeId);
    const outgoing = index.outgoing.get(nodeId) || [];
    const existingIds = new Set(index.nodes.keys());
    const copy = clone(node);
    copy.id = makeId(node.type, options, existingIds);
    delete copy.position;
    return insertNodeAtEdge(workflow, copy, outgoing[0], options);
  }

  function setActionErrorPolicy(workflow, nodeId, policy, options = {}) {
    if (!["stop", "continue", "branch"].includes(policy)) return { ok: false, error: "失败处理策略无效" };
    const index = buildIndex(workflow);
    const node = index.nodes.get(nodeId);
    if (!node || node.type !== "action") return { ok: false, error: "请选择动作节点" };
    const outgoing = index.outgoing.get(nodeId) || [];
    const errorEdge = outgoing.find((edge) => normalizeWhen(edge.when) === "error");
    const normalEdge = outgoing.find((edge) => normalizeWhen(edge.when) === undefined);
    const nodes = clone(workflow.nodes || []);
    let edges = clone(workflow.edges || []);
    const nodeCopy = nodes.find((item) => item.id === nodeId);

    if (policy === "branch") {
      if (!normalEdge) return { ok: false, error: "请先确保动作有一条正常执行路径，再开启错误分支" };
      nodeCopy.on_error = "branch";
      if (!errorEdge) {
        const existingIds = new Set(index.nodes.keys());
        const endNode = {
          id: makeId("end-error", options, existingIds),
          type: "end",
          params: {},
          position: { x: (node.position?.x ?? 170) + 300, y: (node.position?.y ?? 180) + 150 },
        };
        nodes.push(endNode);
        edges.push({ source: nodeId, target: endNode.id, when: "error" });
      }
      return { ok: true, nodes, edges, selectedNodeId: nodeId };
    }

    if (errorEdge) {
      const target = index.nodes.get(errorEdge.target);
      const incoming = index.incoming.get(errorEdge.target) || [];
      if (incoming.length === 1 && target?.type !== "end") {
        return { ok: false, error: "错误分支已经包含后续节点；请先处理该分支，再切换失败策略" };
      }
      edges = edges.filter((edge) => edgeKey(edge) !== edgeKey(errorEdge));
      if (incoming.length === 1 && target?.type === "end") {
        const targetId = target.id;
        for (let i = nodes.length - 1; i >= 0; i -= 1) {
          if (nodes[i].id === targetId) nodes.splice(i, 1);
        }
      }
    }
    nodeCopy.on_error = policy;
    return { ok: true, nodes, edges, selectedNodeId: nodeId };
  }

  function validateGraphStructure(workflow) {
    const errors = [];
    if (!workflow || !Array.isArray(workflow.nodes) || workflow.nodes.length < 1) return ["工作流至少需要一个节点"];
    if (!Array.isArray(workflow.edges)) return ["工作流连线必须是数组"];

    const index = buildIndex(workflow);
    if (index.nodes.size !== workflow.nodes.length) errors.push("节点 ID 重复");
    const seenEdges = new Set();
    for (const edge of workflow.edges) {
      if (!edge || !index.nodes.has(edge.source) || !index.nodes.has(edge.target)) {
        errors.push("连线引用了不存在的节点");
        continue;
      }
      if (edge.source === edge.target) errors.push("节点不能连接到自身");
      const when = normalizeWhen(edge.when);
      if (when !== undefined && !["true", "false", "error"].includes(when)) errors.push("连线条件无效");
      const key = edgeKey(edge);
      if (seenEdges.has(key)) errors.push("存在重复连线");
      seenEdges.add(key);
      if (index.nodes.get(edge.source)?.type === "end") errors.push("结束节点不能有后继连线");
    }

    for (const node of workflow.nodes) {
      const outgoing = index.outgoing.get(node.id) || [];
      const labels = outgoing.map((edge) => normalizeWhen(edge.when));
      if (node.type === "end") {
        if (outgoing.length !== 0) errors.push("结束节点不能有后继连线");
      } else if (node.type === "condition") {
        if (outgoing.length !== 2 || new Set(labels).size !== 2 || !labels.includes("true") || !labels.includes("false")) {
          errors.push("条件节点必须有 true 和 false 两条出口");
        }
      } else if (node.type === "action" && node.on_error === "branch") {
        if (outgoing.length !== 2 || new Set(labels).size !== 2 || !labels.includes(undefined) || !labels.includes("error")) {
          errors.push("错误分支动作必须有正常和 error 两条出口");
        }
      } else if (outgoing.length !== 1 || normalizeWhen(outgoing[0]?.when) !== undefined) {
        errors.push("普通节点必须且只能有一条常规出口");
      }
    }

    const roots = workflow.nodes.filter((node) => (index.incoming.get(node.id) || []).length === 0);
    if (roots.length !== 1) errors.push("工作流必须且只能有一个起点");

    const color = new Map(workflow.nodes.map((node) => [node.id, 0]));
    let hasCycle = false;
    function visit(id) {
      color.set(id, 1);
      for (const edge of index.outgoing.get(id) || []) {
        if (color.get(edge.target) === 1) hasCycle = true;
        else if (color.get(edge.target) === 0) visit(edge.target);
      }
      color.set(id, 2);
    }
    for (const node of workflow.nodes) if (color.get(node.id) === 0) visit(node.id);
    if (hasCycle) errors.push("工作流不允许存在循环");

    if (roots.length === 1) {
      const reachable = new Set();
      const queue = [roots[0].id];
      while (queue.length) {
        const id = queue.shift();
        if (reachable.has(id)) continue;
        reachable.add(id);
        for (const edge of index.outgoing.get(id) || []) queue.push(edge.target);
      }
      if (reachable.size !== workflow.nodes.length) errors.push("存在无法从起点到达的节点");
      if (!workflow.nodes.some((node) => node.type === "end" && reachable.has(node.id))) errors.push("工作流必须包含可到达的结束节点");
    }
    return errors;
  }

  function createHistory(limit = 80) {
    const undoStack = [];
    const redoStack = [];
    function trim(stack) {
      while (stack.length > limit) stack.shift();
    }
    return {
      push(workflow) {
        undoStack.push(snapshot(workflow));
        trim(undoStack);
        redoStack.length = 0;
      },
      pushSnapshot(state) {
        if (!state) return;
        undoStack.push(clone(state));
        trim(undoStack);
        redoStack.length = 0;
      },
      undo(current) {
        if (!undoStack.length) return null;
        redoStack.push(snapshot(current));
        trim(redoStack);
        return undoStack.pop();
      },
      redo(current) {
        if (!redoStack.length) return null;
        undoStack.push(snapshot(current));
        trim(undoStack);
        return redoStack.pop();
      },
      clear() {
        undoStack.length = 0;
        redoStack.length = 0;
      },
      get canUndo() { return undoStack.length > 0; },
      get canRedo() { return redoStack.length > 0; },
    };
  }

  return {
    snapshot,
    restore,
    edgeKey,
    buildIndex,
    getRootNode,
    getVirtualRootEdge,
    resolveInsertEdge,
    insertNodeAtEdge,
    addEndNode,
    connectNodes,
    removeEdge,
    canDeleteNode,
    removeNode,
    canDuplicateNode,
    duplicateNode,
    setActionErrorPolicy,
    validateGraphStructure,
    createHistory,
  };
});
