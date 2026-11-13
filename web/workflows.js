const ui = {
  workflowSelect: document.getElementById("workflowSelect"),
  workflowName: document.getElementById("workflowName"),
  workflowDescription: document.getElementById("workflowDescription"),
  workflowVersion: document.getElementById("workflowVersion"),
  newWorkflow: document.getElementById("newWorkflow"),
  copyWorkflow: document.getElementById("copyWorkflow"),
  saveWorkflow: document.getElementById("saveWorkflow"),
  deleteWorkflow: document.getElementById("deleteWorkflow"),
  validateWorkflow: document.getElementById("validateWorkflow"),
  dryRunWorkflow: document.getElementById("dryRunWorkflow"),
  toggleWorkflow: document.getElementById("toggleWorkflow"),
  actionLibrary: document.getElementById("actionLibrary"),
  triggerType: document.getElementById("triggerType"),
  triggerFields: document.getElementById("triggerFields"),
  edgeWhen: document.getElementById("edgeWhen"),
  linkMode: document.getElementById("linkMode"),
  autoArrange: document.getElementById("autoArrange"),
  zoomOut: document.getElementById("zoomOut"),
  zoomIn: document.getElementById("zoomIn"),
  zoomLabel: document.getElementById("zoomLabel"),
  validationMessage: document.getElementById("validationMessage"),
  canvasViewport: document.getElementById("canvasViewport"),
  canvasWorld: document.getElementById("canvasWorld"),
  edgeLayer: document.getElementById("edgeLayer"),
  canvasNodes: document.getElementById("canvasNodes"),
  triggerBadge: document.getElementById("triggerBadge"),
  inspectorContent: document.getElementById("inspectorContent"),
  duplicateNode: document.getElementById("duplicateNode"),
  deleteNode: document.getElementById("deleteNode"),
  runList: document.getElementById("runList"),
  displayConnection: document.getElementById("displayConnection"),
};

const GESTURES = ["Open_Palm", "Closed_Fist", "Thumb_Up", "Thumb_Down", "Pointing_Up", "Victory", "ILoveYou"];
const GESTURE_LABELS = {
  Open_Palm: "张开手掌", Closed_Fist: "握拳", Thumb_Up: "竖拇指", Thumb_Down: "拇指向下",
  Pointing_Up: "食指向上", Victory: "V 字手势", ILoveYou: "我爱你手势",
};
const ACTION_LABELS = {
  "web.navigate_route": "切换页面", "web.set_scene": "切换展厅场景", "web.show_panel": "显示面板",
  "web.hide_panel": "隐藏面板", "web.set_text": "设置展示文本", "web.return_home": "返回首页",
  "video.load": "加载视频", "video.play": "播放视频", "video.pause": "暂停视频",
  "video.seek": "跳转进度", "video.set_volume": "设置音量", "video.mute": "静音",
  "video.unmute": "取消静音", "video.set_loop": "设置循环播放", "ppt.open_deck": "打开 PPT",
  "ppt.start_slideshow": "开始放映", "ppt.next_slide": "下一页", "ppt.previous_slide": "上一页",
  "ppt.goto_slide": "跳转幻灯片", "ppt.end_slideshow": "结束放映",
};
const NODE_LABELS = { action: "动作", condition: "条件", delay: "延迟", wait_event: "等待事件", end: "结束" };
const NODE_TYPES = ["action", "condition", "delay", "wait_event", "end"];

let workflows = [];
let workflow = null;
let actionDefinitions = [];
let selectedNodeId = null;
let linkSourceId = null;
let zoom = 1;
let activeRunId = null;
const nodeStatuses = new Map();

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(result.detail) ? result.detail.join("；") : result.detail;
    throw new Error(detail || "请求失败");
  }
  return result;
}

function make(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function currentNode() {
  return workflow?.nodes.find((node) => node.id === selectedNodeId) || null;
}

function setMessage(message, state = "ok") {
  ui.validationMessage.textContent = message;
  ui.validationMessage.dataset.state = state;
}

function setEditingEnabled(enabled) {
  [ui.copyWorkflow, ui.saveWorkflow, ui.deleteWorkflow, ui.validateWorkflow, ui.dryRunWorkflow, ui.toggleWorkflow].forEach((button) => {
    button.disabled = !enabled;
  });
  ui.workflowName.disabled = !enabled;
  ui.workflowDescription.disabled = !enabled;
  ui.workflowVersion.disabled = !enabled;
  ui.triggerType.disabled = !enabled;
}

function refreshHeader() {
  const hasWorkflow = Boolean(workflow);
  setEditingEnabled(hasWorkflow);
  ui.workflowName.value = workflow?.name || "";
  ui.workflowDescription.value = workflow?.description || "";
  ui.toggleWorkflow.textContent = workflow?.enabled ? "禁用" : "启用";
  ui.workflowSelect.value = workflow?.id || "";
}

function updateHeaderData() {
  if (!workflow) return;
  workflow.name = ui.workflowName.value;
  workflow.description = ui.workflowDescription.value;
}

function renderWorkflowOptions() {
  ui.workflowSelect.replaceChildren();
  const empty = make("option", "", workflows.length ? "选择工作流" : "暂无工作流");
  empty.value = "";
  ui.workflowSelect.append(empty);
  for (const item of workflows) {
    const option = make("option", "", item.name + (item.enabled ? " · 已启用" : ""));
    option.value = item.id;
    ui.workflowSelect.append(option);
  }
  ui.workflowSelect.value = workflow?.id || "";
}

async function reloadWorkflowList() {
  const response = await api("/api/workflows");
  workflows = response.workflows;
  renderWorkflowOptions();
}

async function loadWorkflow(workflowId) {
  if (!workflowId) return;
  const response = await api("/api/workflows/" + encodeURIComponent(workflowId));
  workflow = response.workflow;
  selectedNodeId = null;
  linkSourceId = null;
  nodeStatuses.clear();
  activeRunId = null;
  await loadVersions();
  refreshHeader();
  renderTrigger();
  renderCanvas();
  renderInspector();
  await reloadWorkflowList();
}

async function loadVersions() {
  if (!workflow) return;
  const response = await api("/api/workflows/" + encodeURIComponent(workflow.id) + "/versions");
  ui.workflowVersion.replaceChildren();
  for (const item of response.versions) {
    const option = make("option", "", "v" + item.version);
    option.value = String(item.version);
    ui.workflowVersion.append(option);
  }
  ui.workflowVersion.value = String(workflow.version);
}

function renderActionLibrary() {
  ui.actionLibrary.replaceChildren(make("h2", "", "动作"));
  const actions = [...actionDefinitions];
  if (actions.length === 0) {
    ui.actionLibrary.append(make("p", "muted", "暂无可用动作"));
    return;
  }
  for (const action of actions) {
    const button = make("button", "library-node action-library-item");
    button.type = "button";
    button.draggable = true;
    button.dataset.action = action.name;
    button.append(make("span", "node-mark action-mark", "→"), make("span", "", ACTION_LABELS[action.name] || action.name));
    button.title = action.name;
    button.addEventListener("click", () => addNode({ type: "action", action: action.name, params: {} }));
    button.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", "action:" + action.name);
      event.dataTransfer.effectAllowed = "copy";
    });
    ui.actionLibrary.append(button);
  }
}

function defaultNode(type, action = "") {
  const id = type + "-" + crypto.randomUUID().slice(0, 8);
  if (type === "action") return { id, type, action, params: {}, timeout_ms: 5000, on_error: "stop", retries: 0 };
  if (type === "condition") return { id, type, params: { field: "confidence", operator: "gte", value: 0.6 } };
  if (type === "delay") return { id, type, params: { delay_ms: 500 } };
  if (type === "wait_event") return { id, type, params: { event: "gesture", gesture: "Open_Palm" }, timeout_ms: 10000 };
  return { id, type: "end", params: {} };
}

function addNode(node) {
  if (!workflow) return;
  if (node.type === "condition") {
    addConditionNode(node);
    return;
  }
  const requestedPosition = node.position;
  const edge = findInsertEdge();
  if (!edge) {
    if (node.type === "end") {
      const sourceNode = findNode(selectedNodeId);
      if (sourceNode && sourceNode.type !== "end") {
        const when = sourceNode.type === "condition" ? (ui.edgeWhen.value || undefined) : undefined;
        if (workflow.edges.some((item) => item.source === sourceNode.id && item.when === when)) {
          setMessage("所选路径已经有后继节点", "error");
          return;
        }
        node.position = requestedPosition || { x: sourceNode.position.x + 300, y: sourceNode.position.y };
        workflow.nodes.push(node);
        const newEdge = { source: sourceNode.id, target: node.id };
        if (when) newEdge.when = when;
        workflow.edges.push(newEdge);
        selectedNodeId = node.id;
        renderCanvas();
        renderInspector();
        return;
      }
    }
    setMessage("请选择一条普通执行路径再插入节点", "error");
    return;
  }
  const source = edge.source;
  const target = edge.target;
  workflow.edges = workflow.edges.filter((item) => item !== edge);
  const previousTarget = findNode(target);
  if (node.type === "end") {
    if (previousTarget?.type === "end" && workflow.edges.every((item) => item.target !== target && item.source !== target)) {
      workflow.nodes = workflow.nodes.filter((item) => item.id !== target);
    }
    node.position = requestedPosition || { x: findNode(source)?.position?.x + 300 || 470, y: previousTarget?.position?.y || 180 };
    workflow.nodes.push(node);
    if (source) {
      const ending = { source, target: node.id };
      if (edge.when) ending.when = edge.when;
      workflow.edges.push(ending);
    }
    selectedNodeId = node.id;
    renderCanvas();
    renderInspector();
    return;
  }
  node.position = requestedPosition || { x: source ? (findNode(source)?.position?.x || 100) + 300 : 170, y: findNode(target)?.position?.y || 180 };
  workflow.nodes.push(node);
  if (source) {
    const upstream = { source, target: node.id };
    if (edge.when) upstream.when = edge.when;
    workflow.edges.push(upstream);
  }
  workflow.edges.push({ source: node.id, target });
  selectedNodeId = node.id;
  clearMessage();
  renderCanvas();
  renderInspector();
}

function addConditionNode(node) {
  const end = workflow.nodes.find((item) => item.type === "end" && workflow.edges.some((edge) => edge.target === item.id));
  let incoming = end && workflow.edges.find((edge) => edge.target === end.id && edge.when === undefined);
  if (!end) {
    const loneEnd = workflow.nodes.find((item) => item.type === "end");
    if (loneEnd && workflow.edges.length === 0) {
      workflow.nodes = workflow.nodes.filter((item) => item.id !== loneEnd.id);
      node.position = { x: 170, y: 240 };
      workflow.nodes.push(node);
      addConditionEnds(node);
      return;
    }
  }
  if (!incoming) {
    setMessage("条件分支只能插入到一个普通执行路径的结束位置", "error");
    return;
  }
  const oldEndId = end.id;
  const previousId = incoming.source;
  node.position = { x: (findNode(previousId)?.position?.x || 100) + 300, y: findNode(oldEndId)?.position?.y || 180 };
  workflow.edges = workflow.edges.filter((edge) => edge !== incoming && edge.target !== oldEndId);
  workflow.nodes = workflow.nodes.filter((item) => item.id !== oldEndId);
  workflow.nodes.push(node);
  workflow.edges.push({ source: previousId, target: node.id });
  addConditionEnds(node);
}

function addConditionEnds(node) {
  const yes = { id: "end-yes-" + crypto.randomUUID().slice(0, 6), type: "end", params: {}, position: { x: node.position.x + 320, y: node.position.y - 70 } };
  const no = { id: "end-no-" + crypto.randomUUID().slice(0, 6), type: "end", params: {}, position: { x: node.position.x + 320, y: node.position.y + 100 } };
  workflow.nodes.push(yes, no);
  workflow.edges.push({ source: node.id, target: yes.id, when: "true" }, { source: node.id, target: no.id, when: "false" });
  selectedNodeId = node.id;
  clearMessage();
  renderCanvas();
  renderInspector();
}

function findInsertEdge() {
  const selected = findNode(selectedNodeId);
  const requestedWhen = ui.edgeWhen.value || undefined;
  if (selected && selected.type !== "end") {
    const edge = workflow.edges.find((item) => item.source === selected.id && item.when === requestedWhen);
    if (edge) return edge;
  }
  return workflow.edges.find((edge) => edge.when === requestedWhen && findNode(edge.target)?.type === "end") || null;
}

function findNode(nodeId) {
  return workflow?.nodes.find((node) => node.id === nodeId) || null;
}

function clearMessage() {
  ui.validationMessage.textContent = "";
  delete ui.validationMessage.dataset.state;
}

function renderTrigger() {
  if (!workflow) return;
  const trigger = workflow.trigger;
  ui.triggerType.value = trigger.type;
  ui.triggerFields.replaceChildren();
  ui.triggerFields.className = "trigger-fields";
  if (trigger.type === "gesture_trigger") {
    const select = gestureSelect(trigger.gesture);
    select.addEventListener("change", () => { trigger.gesture = select.value; renderCanvas(); });
    ui.triggerFields.append(select);
  } else if (trigger.type === "gesture_sequence_trigger") {
    const input = make("input");
    input.type = "text";
    input.value = trigger.gestures.join(",");
    input.placeholder = "Open_Palm,Victory";
    input.setAttribute("aria-label", "手势序列，以逗号分隔");
    input.addEventListener("change", () => { trigger.gestures = input.value.split(",").map((value) => value.trim()).filter(Boolean); renderCanvas(); });
    const windowInput = make("input");
    windowInput.type = "number";
    windowInput.min = "1000";
    windowInput.max = "30000";
    windowInput.step = "500";
    windowInput.value = String(trigger.sequence_window_ms || 5000);
    windowInput.setAttribute("aria-label", "序列时间窗口毫秒");
    windowInput.addEventListener("change", () => { trigger.sequence_window_ms = Number(windowInput.value); });
    ui.triggerFields.append(input, windowInput);
  }
  ui.triggerBadge.textContent = trigger.type === "gesture_trigger"
    ? "手势 · " + (GESTURE_LABELS[trigger.gesture] || trigger.gesture)
    : trigger.type === "gesture_sequence_trigger"
      ? trigger.gestures.map((gesture) => GESTURE_LABELS[gesture] || gesture).join(" → ")
      : "主控锁定";
}

function gestureSelect(value) {
  const select = make("select");
  select.setAttribute("aria-label", "选择手势");
  for (const gesture of GESTURES) {
    const option = make("option", "", GESTURE_LABELS[gesture]);
    option.value = gesture;
    select.append(option);
  }
  select.value = GESTURES.includes(value) ? value : GESTURES[0];
  return select;
}

function renderCanvas() {
  if (!workflow) {
    ui.canvasNodes.replaceChildren();
    drawEdges();
    return;
  }
  ui.canvasNodes.replaceChildren();
  for (const node of workflow.nodes) {
    if (!node.position) node.position = { x: 170 + workflow.nodes.indexOf(node) * 290, y: 180 };
    const card = make("article", "canvas-node node-type-" + node.type);
    card.dataset.nodeId = node.id;
    card.dataset.selected = String(node.id === selectedNodeId);
    card.dataset.linkSource = String(node.id === linkSourceId);
    card.dataset.status = nodeStatuses.get(node.id) || "idle";
    card.style.left = node.position.x + "px";
    card.style.top = node.position.y + "px";
    card.draggable = true;
    const head = make("div", "canvas-node-header");
    head.append(make("span", "", NODE_LABELS[node.type] || node.type), make("span", "canvas-node-title", nodeTitle(node)));
    card.append(head);
    const body = make("div", "canvas-node-body");
    body.append(make("span", "canvas-node-detail", nodeDetail(node)));
    if (node.type === "action" && node.on_error === "branch") body.append(make("span", "canvas-node-detail", "失败时走 error 分支"));
    card.append(body);
    card.addEventListener("click", () => selectOrLink(node.id));
    card.addEventListener("dragstart", (event) => {
      draggingNodeId = node.id;
      event.dataTransfer.setData("text/plain", "node:" + node.id);
      event.dataTransfer.effectAllowed = "move";
    });
    ui.canvasNodes.append(card);
  }
  drawEdges();
}

function nodeTitle(node) {
  if (node.type === "action") return ACTION_LABELS[node.action] || node.action || "未选择动作";
  if (node.type === "condition") return node.params?.field + " " + node.params?.operator;
  if (node.type === "delay") return "延迟 " + (node.params?.delay_ms ?? 0) + " ms";
  if (node.type === "wait_event") return "等待 " + (node.params?.event || "事件");
  return "流程结束";
}

function nodeDetail(node) {
  if (node.type === "action") return node.action + " · " + JSON.stringify(node.params || {});
  if (node.type === "condition") return String(node.params?.value ?? "");
  if (node.type === "wait_event") return node.params?.event === "gesture" ? GESTURE_LABELS[node.params.gesture] || node.params.gesture : node.params?.event;
  return node.type === "end" ? "成功结束" : "按设定时间等待";
}

function drawEdges() {
  const svg = ui.edgeLayer;
  svg.querySelectorAll("path[data-edge], text[data-edge-label]").forEach((element) => element.remove());
  if (!workflow) return;
  const positions = new Map(workflow.nodes.map((node) => [node.id, node.position || { x: 170, y: 180 }]));
  const root = workflow.nodes.find((node) => !workflow.edges.some((edge) => edge.target === node.id));
  if (root) {
    const to = positions.get(root.id);
    drawPath(svg, 132, 130, to.x, to.y + 53, "trigger", "");
  }
  for (const edge of workflow.edges) {
    const from = positions.get(edge.source);
    const to = positions.get(edge.target);
    if (!from || !to) continue;
    drawPath(svg, from.x + 236, from.y + 53, to.x, to.y + 53, edge.when === "error" ? "error" : edge.source, edge.when || "");
  }
}

function drawPath(svg, x1, y1, x2, y2, key, label) {
  const namespace = "http://www.w3.org/2000/svg";
  const path = document.createElementNS(namespace, "path");
  path.dataset.edge = key;
  const bend = Math.max(38, (x2 - x1) / 2);
  path.setAttribute("d", `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
  if (key === "error") path.classList.add("edge-error");
  svg.append(path);
  if (label) {
    const text = document.createElementNS(namespace, "text");
    text.dataset.edgeLabel = key;
    text.setAttribute("x", String((x1 + x2) / 2));
    text.setAttribute("y", String((y1 + y2) / 2 - 7));
    text.textContent = label;
    svg.append(text);
  }
}

function selectOrLink(nodeId) {
  if (ui.linkMode.getAttribute("aria-pressed") === "true") {
    if (!linkSourceId) {
      linkSourceId = nodeId;
      selectedNodeId = nodeId;
      setMessage("已选起点，请再选择目标节点");
    } else if (linkSourceId !== nodeId) {
      const when = ui.edgeWhen.value || undefined;
      workflow.edges = workflow.edges.filter((edge) => !(edge.source === linkSourceId && edge.when === when));
      const edge = { source: linkSourceId, target: nodeId };
      if (when) edge.when = when;
      workflow.edges.push(edge);
      selectedNodeId = nodeId;
      linkSourceId = null;
      ui.linkMode.setAttribute("aria-pressed", "false");
      setMessage("连线已更新，请校验工作流");
    }
    renderCanvas();
    renderInspector();
    return;
  }
  selectedNodeId = nodeId;
  renderCanvas();
  renderInspector();
}

function field(container, labelText, control) {
  const wrapper = make("label", "inspector-field");
  wrapper.append(make("span", "", labelText), control);
  container.append(wrapper);
  return control;
}

function inputControl(value, type = "text", attributes = {}) {
  const input = make("input");
  input.type = type;
  input.value = value ?? "";
  for (const [name, item] of Object.entries(attributes)) input.setAttribute(name, String(item));
  return input;
}

function bindNodeValue(control, update) {
  const handler = () => {
    update(control.type === "checkbox" ? control.checked : control.type === "number" ? Number(control.value) : control.value);
    renderCanvas();
  };
  control.addEventListener("input", handler);
  control.addEventListener("change", handler);
}

function renderInspector() {
  ui.inspectorContent.replaceChildren();
  const node = currentNode();
  ui.duplicateNode.disabled = !node || node.type === "condition" || node.type === "end";
  ui.deleteNode.disabled = !node;
  if (!node) {
    ui.inspectorContent.append(make("p", "muted", "选择画布节点"));
    return;
  }
  const idInput = inputControl(node.id, "text", { maxlength: 64, readonly: true });
  field(ui.inspectorContent, "节点 ID", idInput);
  if (node.type === "action") renderActionProperties(node);
  if (node.type === "condition") renderConditionProperties(node);
  if (node.type === "delay") {
    const delay = inputControl(node.params.delay_ms, "number", { min: 0, max: 30000, step: 100 });
    field(ui.inspectorContent, "延迟（毫秒）", delay);
    bindNodeValue(delay, (value) => { node.params.delay_ms = value; });
  }
  if (node.type === "wait_event") renderWaitEventProperties(node);
  if (node.type === "action" || node.type === "wait_event") {
    const timeout = inputControl(node.timeout_ms || 5000, "number", { min: 100, max: 60000, step: 100 });
    field(ui.inspectorContent, "超时（毫秒）", timeout);
    bindNodeValue(timeout, (value) => { node.timeout_ms = value; });
  }
  if (node.type === "action") {
    const errorPath = make("select");
    for (const [value, label] of [["stop", "失败即停止"], ["continue", "失败后继续"], ["branch", "走错误分支"]]) {
      const option = make("option", "", label); option.value = value; errorPath.append(option);
    }
    errorPath.value = node.on_error || "stop";
    field(ui.inspectorContent, "失败处理", errorPath);
    bindNodeValue(errorPath, (value) => { node.on_error = value; renderInspector(); });
    const retries = inputControl(node.retries || 0, "number", { min: 0, max: 2, step: 1 });
    field(ui.inspectorContent, "幂等重试次数", retries);
    bindNodeValue(retries, (value) => { node.retries = value; });
  }
}

function renderActionProperties(node) {
  const select = make("select");
  for (const action of actionDefinitions) {
    const option = make("option", "", ACTION_LABELS[action.name] || action.name);
    option.value = action.name;
    select.append(option);
  }
  select.value = node.action;
  field(ui.inspectorContent, "动作", select);
  select.addEventListener("change", () => {
    node.action = select.value;
    node.params = {};
    const schema = actionDefinitions.find((item) => item.name === node.action)?.schema;
    for (const name of schema?.required || []) {
      const rule = schema.properties[name];
      node.params[name] = rule.enum?.[0] ?? rule.minimum ?? (rule.type === "boolean" ? false : "");
    }
    renderInspector();
    renderCanvas();
  });
  const schema = actionDefinitions.find((item) => item.name === node.action)?.schema;
  if (!schema) {
    ui.inspectorContent.append(make("p", "muted", "动作未注册"));
    return;
  }
  for (const [name, rule] of Object.entries(schema.properties || {})) {
    let control;
    if (rule.enum) {
      control = make("select");
      if (rule.enum.length === 0) control.append(make("option", "", "未登记可用资源"));
      for (const choice of rule.enum) {
        const option = make("option", "", String(choice)); option.value = String(choice); control.append(option);
      }
      control.value = node.params[name] ?? "";
    } else if (rule.type === "boolean") {
      control = inputControl(Boolean(node.params[name]), "checkbox");
      control.checked = Boolean(node.params[name]);
      control.className = "inspector-checkbox-control";
    } else if (["integer", "number"].includes(rule.type)) {
      control = inputControl(node.params[name] ?? rule.minimum ?? "", "number", {
        min: rule.minimum ?? "", max: rule.maximum ?? "", step: rule.type === "integer" ? 1 : "any",
      });
    } else {
      control = inputControl(node.params[name] ?? "", "text", { maxlength: rule.maxLength || 1000 });
    }
    field(ui.inspectorContent, rule.title || name, control);
    bindNodeValue(control, (value) => { node.params[name] = value; });
  }
}

function renderConditionProperties(node) {
  const fieldSelect = make("select");
  for (const item of ["gesture", "confidence", "handedness", "target_id", "action"]) {
    const option = make("option", "", item); option.value = item; fieldSelect.append(option);
  }
  fieldSelect.value = node.params.field;
  field(ui.inspectorContent, "上下文字段", fieldSelect);
  bindNodeValue(fieldSelect, (value) => { node.params.field = value; renderInspector(); });
  const opSelect = make("select");
  for (const [value, label] of [["eq", "等于"], ["ne", "不等于"], ["gt", ">"], ["gte", "≥"], ["lt", "<"], ["lte", "≤"], ["in", "属于"]]) {
    const option = make("option", "", label); option.value = value; opSelect.append(option);
  }
  opSelect.value = node.params.operator;
  field(ui.inspectorContent, "比较方式", opSelect);
  bindNodeValue(opSelect, (value) => { node.params.operator = value; renderInspector(); });
  const valueControl = inputControl(Array.isArray(node.params.value) ? node.params.value.join(",") : node.params.value, node.params.field === "confidence" ? "number" : "text", { step: "any" });
  field(ui.inspectorContent, "比较值", valueControl);
  bindNodeValue(valueControl, (value) => {
    if (node.params.operator === "in") node.params.value = String(value).split(",").map((item) => item.trim());
    else node.params.value = node.params.field === "confidence" ? Number(value) : value;
  });
}

function renderWaitEventProperties(node) {
  const select = make("select");
  for (const [value, label] of [["gesture", "稳定手势"], ["controller_locked", "主控锁定"], ["controller_lost", "主控丢失"]]) {
    const option = make("option", "", label); option.value = value; select.append(option);
  }
  select.value = node.params.event;
  field(ui.inspectorContent, "等待事件", select);
  bindNodeValue(select, (value) => {
    node.params = value === "gesture" ? { event: value, gesture: "Open_Palm" } : { event: value };
    renderInspector();
    renderCanvas();
  });
  if (node.params.event === "gesture") {
    const gesture = gestureSelect(node.params.gesture);
    field(ui.inspectorContent, "目标手势", gesture);
    bindNodeValue(gesture, (value) => { node.params.gesture = value; });
  }
}

function moveNode(nodeId, clientX, clientY) {
  const node = findNode(nodeId);
  if (!node) return;
  const rect = ui.canvasViewport.getBoundingClientRect();
  node.position = {
    x: Math.max(0, Math.round((clientX - rect.left + ui.canvasViewport.scrollLeft) / zoom - 118)),
    y: Math.max(0, Math.round((clientY - rect.top + ui.canvasViewport.scrollTop) / zoom - 53)),
  };
  renderCanvas();
}

function autoArrange() {
  if (!workflow) return;
  const nodes = new Map(workflow.nodes.map((node) => [node.id, node]));
  const incoming = new Map(workflow.nodes.map((node) => [node.id, 0]));
  const depth = new Map();
  for (const edge of workflow.edges) incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1);
  const queue = workflow.nodes.filter((node) => incoming.get(node.id) === 0).map((node) => node.id);
  queue.forEach((id) => depth.set(id, 0));
  while (queue.length) {
    const id = queue.shift();
    for (const edge of workflow.edges.filter((item) => item.source === id)) {
      depth.set(edge.target, Math.max(depth.get(edge.target) || 0, (depth.get(id) || 0) + 1));
      incoming.set(edge.target, incoming.get(edge.target) - 1);
      if (incoming.get(edge.target) === 0) queue.push(edge.target);
    }
  }
  const rows = new Map();
  for (const node of workflow.nodes) {
    const column = depth.get(node.id) || 0;
    const row = rows.get(column) || 0;
    node.position = { x: 170 + column * 320, y: 90 + row * 175 };
    rows.set(column, row + 1);
  }
  renderCanvas();
}

function updateZoom() {
  ui.canvasWorld.style.transform = "scale(" + zoom + ")";
  ui.zoomLabel.textContent = Math.round(zoom * 100) + "%";
}

async function saveWorkflow() {
  updateHeaderData();
  const response = await api("/api/workflows/" + encodeURIComponent(workflow.id), {
    method: "PUT", body: JSON.stringify(workflow),
  });
  workflow = response.workflow;
  await reloadWorkflowList();
  await loadVersions();
  refreshHeader();
  setMessage("已保存为版本 v" + workflow.version);
}

async function validateCurrent() {
  updateHeaderData();
  const response = await api("/api/workflows/validate", { method: "POST", body: JSON.stringify(workflow) });
  setMessage(response.valid ? "校验通过" : response.errors.join("；"), response.valid ? "ok" : "error");
}

async function createWorkflow() {
  const id = crypto.randomUUID().replaceAll("-", "");
  const now = new Date().toISOString();
  const starter = {
    schema_version: 1, id, name: "新建工作流", description: "", enabled: false,
    trigger: { type: "gesture_trigger", gesture: "Open_Palm" },
    nodes: [
      { id: "play", type: "action", action: "video.play", params: {}, timeout_ms: 3000, on_error: "stop", position: { x: 170, y: 80 } },
      { id: "end", type: "end", params: {}, position: { x: 470, y: 80 } },
    ], edges: [{ source: "play", target: "end" }], version: 1, created_at: now, updated_at: now,
  };
  const response = await api("/api/workflows", { method: "POST", body: JSON.stringify(starter) });
  await reloadWorkflowList();
  await loadWorkflow(response.workflow.id);
  setMessage("已创建工作流");
}

async function toggleWorkflow() {
  await saveWorkflow();
  const operation = workflow.enabled ? "disable" : "enable";
  const response = await api(`/api/workflows/${encodeURIComponent(workflow.id)}/${operation}`, { method: "POST" });
  workflow = response.workflow;
  refreshHeader();
  await reloadWorkflowList();
  setMessage(workflow.enabled ? "工作流已启用" : "工作流已禁用");
}

async function duplicateWorkflow() {
  const response = await api(`/api/workflows/${encodeURIComponent(workflow.id)}/copy`, { method: "POST" });
  await reloadWorkflowList();
  await loadWorkflow(response.workflow.id);
  setMessage("已复制工作流");
}

async function deleteWorkflow() {
  if (!workflow || !window.confirm(`确定删除“${workflow.name}”吗？此操作不可撤销。`)) return;
  await api("/api/workflows/" + encodeURIComponent(workflow.id), { method: "DELETE" });
  workflow = null;
  selectedNodeId = null;
  await reloadWorkflowList();
  if (workflows.length) await loadWorkflow(workflows[0].id);
  else {
    refreshHeader();
    renderCanvas();
    renderInspector();
  }
  setMessage("工作流已删除");
}

async function dryRun() {
  await saveWorkflow();
  const response = await api(`/api/workflows/${encodeURIComponent(workflow.id)}/dry-run`, { method: "POST", body: JSON.stringify({ context: { gesture: "Open_Palm", confidence: 0.9, handedness: "Right", target_id: "simulation", action: "play_pause" } }) });
  const run = response.run;
  nodeStatuses.clear();
  for (const step of run.steps || []) nodeStatuses.set(step.node_id, step.status);
  renderCanvas();
  setMessage(run.status === "success" ? "模拟成功 · " + run.steps.length + " 个节点" : run.error || "模拟失败", run.status === "success" ? "ok" : "error");
  await refreshRuns();
}

async function refreshRuns() {
  const response = await api("/api/workflow-runs?limit=30");
  ui.runList.replaceChildren();
  if (!response.runs.length) {
    ui.runList.append(make("p", "muted", "暂无运行记录"));
    return;
  }
  const names = new Map(workflows.map((item) => [item.id, item.name]));
  for (const run of response.runs) {
    const entry = make("article", "run-entry");
    entry.dataset.status = run.status;
    entry.append(make("span", "run-dot"));
    const text = make("div");
    text.append(make("div", "run-name", names.get(run.workflow_id) || run.workflow_id));
    text.append(make("div", "run-detail", run.mode + " · " + run.status + " · " + new Date(run.created_at).toLocaleTimeString()));
    entry.append(text);
    const detailButton = make("button", "", "步骤");
    detailButton.type = "button";
    const stepPanel = make("div", "run-steps");
    stepPanel.hidden = true;
    detailButton.addEventListener("click", async () => {
      if (stepPanel.hidden) {
        const detail = await api("/api/workflow-runs/" + encodeURIComponent(run.run_id));
        stepPanel.replaceChildren();
        for (const step of detail.run.steps) {
          const row = make("div", "run-step");
          row.append(make("span", "run-step-name", step.node_id));
          row.append(make("span", "run-step-status", step.status));
          if (step.error) row.append(make("span", "run-step-error", step.error));
          stepPanel.append(row);
        }
        if (detail.run.error) stepPanel.append(make("p", "run-step-error", detail.run.error));
        if (!detail.run.steps.length && !detail.run.error) stepPanel.append(make("p", "muted", "暂无步骤"));
        stepPanel.hidden = false;
        detailButton.textContent = "收起";
      } else {
        stepPanel.hidden = true;
        detailButton.textContent = "步骤";
      }
    });
    entry.append(detailButton);
    entry.append(stepPanel);
    ui.runList.append(entry);
  }
}

async function refreshDisplayStatus() {
  const response = await api("/api/workflow-status");
  const online = response.display_connected;
  ui.displayConnection.dataset.state = online ? "online" : "offline";
  ui.displayConnection.textContent = online ? "展示页面已连接" : "展示页面未连接";
}

function connectWorkflowEvents() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(protocol + "//" + location.host + "/ws/events");
  socket.addEventListener("message", async (message) => {
    try {
      const event = JSON.parse(message.data);
      if (event.type === "workflow") {
        if (event.run_id && event.status === "pending") {
          activeRunId = event.run_id;
          nodeStatuses.clear();
          renderCanvas();
        }
        setMessage(`运行 ${event.status}${event.error ? " · " + event.error : ""}`, ["failed", "timeout"].includes(event.status) ? "error" : "ok");
        await refreshRuns();
      } else if (event.type === "workflow_step") {
        if (event.run_id === activeRunId && event.workflow_id === workflow?.id) {
          nodeStatuses.set(event.node_id, event.status);
          renderCanvas();
        }
        await refreshRuns();
      }
    } catch (error) {
      console.error("工作流事件解析失败", error);
    }
  });
  socket.addEventListener("close", () => window.setTimeout(connectWorkflowEvents, 1500));
}

function duplicateNode() {
  const node = currentNode();
  if (!node || ["condition", "end"].includes(node.type)) return;
  const edge = workflow.edges.find((item) => item.target === node.id && item.when === undefined);
  const next = workflow.edges.find((item) => item.source === node.id && item.when === undefined);
  if (!edge || !next) {
    setMessage("此节点没有可复制的普通执行路径", "error");
    return;
  }
  const clone = structuredClone(node);
  clone.id = node.type + "-" + crypto.randomUUID().slice(0, 8);
  clone.position = { x: node.position.x + 28, y: node.position.y + 130 };
  workflow.nodes.push(clone);
  workflow.edges = workflow.edges.filter((item) => item !== edge);
  workflow.edges.push({ source: edge.source, target: clone.id }, { source: clone.id, target: node.id });
  selectedNodeId = clone.id;
  renderCanvas();
  renderInspector();
}

function deleteNode() {
  if (!currentNode()) return;
  const deleted = selectedNodeId;
  workflow.nodes = workflow.nodes.filter((node) => node.id !== deleted);
  workflow.edges = workflow.edges.filter((edge) => edge.source !== deleted && edge.target !== deleted);
  selectedNodeId = null;
  renderCanvas();
  renderInspector();
  setMessage("节点已移除；请连接剩余节点并校验", "error");
}

async function initialize() {
  try {
    const [actionResponse, workflowResponse] = await Promise.all([api("/api/actions"), api("/api/workflows")]);
    actionDefinitions = actionResponse.actions;
    workflows = workflowResponse.workflows;
    renderActionLibrary();
    renderWorkflowOptions();
    if (workflows.length) await loadWorkflow(workflows[0].id);
    else {
      setEditingEnabled(false);
      renderCanvas();
    }
    await refreshRuns();
    await refreshDisplayStatus();
  } catch (error) {
    setMessage(error.message, "error");
  }
}

ui.newWorkflow.addEventListener("click", () => createWorkflow().catch((error) => setMessage(error.message, "error")));
ui.copyWorkflow.addEventListener("click", () => duplicateWorkflow().catch((error) => setMessage(error.message, "error")));
ui.deleteWorkflow.addEventListener("click", () => deleteWorkflow().catch((error) => setMessage(error.message, "error")));
ui.saveWorkflow.addEventListener("click", () => saveWorkflow().catch((error) => setMessage(error.message, "error")));
ui.validateWorkflow.addEventListener("click", () => validateCurrent().catch((error) => setMessage(error.message, "error")));
ui.dryRunWorkflow.addEventListener("click", () => dryRun().catch((error) => setMessage(error.message, "error")));
ui.toggleWorkflow.addEventListener("click", () => toggleWorkflow().catch((error) => setMessage(error.message, "error")));
ui.workflowSelect.addEventListener("change", () => loadWorkflow(ui.workflowSelect.value).catch((error) => setMessage(error.message, "error")));
ui.workflowName.addEventListener("input", updateHeaderData);
ui.workflowDescription.addEventListener("input", updateHeaderData);
ui.triggerType.addEventListener("change", () => {
  if (!workflow) return;
  const type = ui.triggerType.value;
  workflow.trigger = type === "gesture_trigger" ? { type, gesture: "Open_Palm" }
    : type === "gesture_sequence_trigger" ? { type, gestures: ["Open_Palm", "Victory"], sequence_window_ms: 5000 }
      : { type };
  renderTrigger();
  renderCanvas();
});
ui.workflowVersion.addEventListener("change", async () => {
  if (!workflow) return;
  const response = await api("/api/workflows/" + encodeURIComponent(workflow.id) + "/versions");
  const item = response.versions.find((version) => String(version.version) === ui.workflowVersion.value);
  if (!item) return;
  const enabled = workflow.enabled;
  workflow = structuredClone(item.definition);
  workflow.enabled = enabled;
  selectedNodeId = null;
  refreshHeader();
  renderTrigger();
  renderCanvas();
  renderInspector();
  setMessage("已载入 v" + item.version + "，保存后将创建新版本");
});

document.querySelectorAll(".library-node[data-node-type]").forEach((button) => {
  button.draggable = true;
  button.addEventListener("click", () => addNode(defaultNode(button.dataset.nodeType)));
  button.addEventListener("dragstart", (event) => {
    event.dataTransfer.setData("text/plain", "node-type:" + button.dataset.nodeType);
    event.dataTransfer.effectAllowed = "copy";
  });
});
ui.linkMode.addEventListener("click", () => {
  const active = ui.linkMode.getAttribute("aria-pressed") !== "true";
  ui.linkMode.setAttribute("aria-pressed", String(active));
  linkSourceId = null;
  if (active) setMessage("选择起点，再选择目标节点");
  else clearMessage();
  renderCanvas();
});
ui.autoArrange.addEventListener("click", autoArrange);
ui.zoomIn.addEventListener("click", () => { zoom = Math.min(1.5, zoom + 0.1); updateZoom(); });
ui.zoomOut.addEventListener("click", () => { zoom = Math.max(0.6, zoom - 0.1); updateZoom(); });
ui.duplicateNode.addEventListener("click", duplicateNode);
ui.deleteNode.addEventListener("click", deleteNode);

ui.canvasViewport.addEventListener("dragover", (event) => event.preventDefault());
ui.canvasViewport.addEventListener("drop", (event) => {
  event.preventDefault();
  const payload = event.dataTransfer.getData("text/plain");
  const rect = ui.canvasViewport.getBoundingClientRect();
  const position = {
    x: Math.max(20, Math.round((event.clientX - rect.left + ui.canvasViewport.scrollLeft) / zoom)),
    y: Math.max(20, Math.round((event.clientY - rect.top + ui.canvasViewport.scrollTop) / zoom)),
  };
  if (payload.startsWith("node:")) {
    moveNode(payload.slice(5), event.clientX, event.clientY);
  } else if (payload.startsWith("node-type:")) {
    const node = defaultNode(payload.slice(10)); node.position = position; addNode(node);
  } else if (payload.startsWith("action:")) {
    const node = defaultNode("action", payload.slice(7)); node.position = position; addNode(node);
  }
});

setInterval(() => {
  refreshRuns().catch(() => {});
  refreshDisplayStatus().catch(() => {});
}, 3000);
connectWorkflowEvents();
initialize();
