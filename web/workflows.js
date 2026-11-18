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
  undoWorkflow: document.getElementById("undoWorkflow"),
  redoWorkflow: document.getElementById("redoWorkflow"),
  toggleWorkflow: document.getElementById("toggleWorkflow"),
  actionLibrary: document.getElementById("actionLibrary"),
  triggerType: document.getElementById("triggerType"),
  triggerFields: document.getElementById("triggerFields"),
  edgeWhen: document.getElementById("edgeWhen"),
  linkMode: document.getElementById("linkMode"),
  pointerMode: document.getElementById("pointerMode"),
  pointerMirror: document.getElementById("pointerMirror"),
  pointerCalibrate: document.getElementById("pointerCalibrate"),
  pointerDiagnostics: document.getElementById("pointerDiagnostics"),
  pointerDiagnosticsPanel: document.getElementById("pointerDiagnosticsPanel"),
  pointerDiagnosticsClose: document.getElementById("pointerDiagnosticsClose"),
  pointerDiagnosticsReset: document.getElementById("pointerDiagnosticsReset"),
  pointerDiagnosticsExport: document.getElementById("pointerDiagnosticsExport"),
  pointerDiagRate: document.getElementById("pointerDiagRate"),
  pointerDiagGap: document.getElementById("pointerDiagGap"),
  pointerDiagRaf: document.getElementById("pointerDiagRaf"),
  pointerDiagProcess: document.getElementById("pointerDiagProcess"),
  pointerDiagDrag: document.getElementById("pointerDiagDrag"),
  pointerDiagCoalesced: document.getElementById("pointerDiagCoalesced"),
  pointerDiagState: document.getElementById("pointerDiagState"),
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
  "web.navigate_route": "打开管理页面", "web.navigate_page": "切换展示主页", "web.navigate_parent": "返回父页面", "web.set_scene": "切换展厅场景", "web.show_panel": "显示面板",
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
let selectedEdgeKey = null;
let linkHistoryBefore = null;
let mouseHistoryBefore = null;
let pointerHistoryBefore = null;
let propertyHistoryBefore = null;
const graphHistory = window.WorkflowGraph.createHistory(80);
let linkSourceId = null;
let zoom = 1;
let activeRunId = null;
const nodeStatuses = new Map();
const nodeCardsById = new Map();
const nodeModelsById = new Map();
let edgeRecords = new Map();
let edgeKeysByNode = new Map();
const POINTER_CALIBRATION_KEY = "gesture-workflow-pointer-calibration-v1";
const POINTER_MIRROR_KEY = "gesture-workflow-pointer-mirror-v1";
let pointerModeEnabled = false;
let pointerMirrorX = loadPointerMirrorPreference();
let pointerPressed = false;
let pointerDownTarget = null;
let pointerDragNodeId = null;
let pointerDownPoint = null;
let pointerGrabOffset = null;
let pointerMoved = false;
let mouseDragOffset = null;
// PointerEventBuffer is exposed by its UMD wrapper as a namespace object.
 // Keep the editor usable even if the optional hand-pointer helper failed to load.
const PointerEventBufferClass = window.PointerEventBuffer?.PointerEventBuffer;
const pointerEventBuffer = typeof PointerEventBufferClass === "function"
  ? new PointerEventBufferClass()
  : null;
let pointerAnimationFrame = null;
let pointerDiagnosticsTimer = null;
let pointerCalibrationSession = null;
const POINTER_METRIC_SAMPLE_LIMIT = 240;
const pointerMetrics = {
  receivedTimes: [], eventGaps: [], rafWaits: [], processDurations: [], dragDurations: [], eventHistory: [],
  lastReceivedAt: null, lastReceivedPressed: null, lastReceivedActive: null, lastIdentityRejected: false,
  lastRafScheduledAt: null, received: 0, processed: 0, coalesced: 0, pressTransitions: 0,
  releaseTransitions: 0, dropouts: 0, identityRejects: 0, dragStarts: 0, dragReleases: 0,
  dragCancels: 0, currentState: "等待指针事件",
};
let pointerIgnoreUntilRelease = false;
let lastPointerPressed = false;
const POINTER_CALIBRATION_TARGETS = [
  { x: 0.08, y: 0.08, label: "左上" },
  { x: 0.92, y: 0.08, label: "右上" },
  { x: 0.92, y: 0.92, label: "右下" },
  { x: 0.08, y: 0.92, label: "左下" },
];
let pointerCalibration = loadPointerCalibration();
const handPointerCursor = make("div", "hand-pointer-cursor");
handPointerCursor.hidden = true;
handPointerCursor.setAttribute("aria-hidden", "true");
document.body.append(handPointerCursor);
const pointerCalibrationOverlay = make("div", "pointer-calibration-overlay");
pointerCalibrationOverlay.hidden = true;
pointerCalibrationOverlay.setAttribute("aria-hidden", "true");
const pointerCalibrationHint = make("div", "pointer-calibration-hint");
const pointerCalibrationTarget = make("div", "pointer-calibration-target");
pointerCalibrationOverlay.append(pointerCalibrationHint, pointerCalibrationTarget);
document.body.append(pointerCalibrationOverlay);

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

function loadPointerMirrorPreference() {
  try {
    return localStorage.getItem(POINTER_MIRROR_KEY) === "true";
  } catch (_error) {
    return false;
  }
}

function pushMetricSample(samples, value) {
  if (!Number.isFinite(value)) return;
  samples.push(value);
  if (samples.length > POINTER_METRIC_SAMPLE_LIMIT) samples.shift();
}

function metricPercentile(samples, percentile) {
  if (!samples.length) return null;
  const sorted = [...samples].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * percentile) - 1)];
}

function metricMaximum(samples) {
  return samples.length ? Math.max(...samples) : null;
}

function updatePointerDiagnostics() {
  if (!ui.pointerDiagnosticsPanel || ui.pointerDiagnosticsPanel.hidden) return;
  const now = performance.now();
  const recentTimes = pointerMetrics.receivedTimes.filter((value) => now - value <= 5000);
  let rate = 0;
  if (recentTimes.length > 1) {
    const span = recentTimes[recentTimes.length - 1] - recentTimes[0];
    if (span > 0) rate = (recentTimes.length - 1) * 1000 / span;
  }
  const stale = pointerMetrics.lastReceivedAt === null || now - pointerMetrics.lastReceivedAt > 1500;
  if (stale) rate = 0;
  const formatMs = (value) => value === null ? "--" : value.toFixed(1) + " ms";
  ui.pointerDiagRate.textContent = rate.toFixed(1) + " Hz";
  ui.pointerDiagGap.textContent = formatMs(metricPercentile(pointerMetrics.eventGaps, 0.95));
  ui.pointerDiagRaf.textContent = formatMs(metricPercentile(pointerMetrics.rafWaits, 0.95));
  ui.pointerDiagProcess.textContent = formatMs(metricMaximum(pointerMetrics.processDurations));
  ui.pointerDiagDrag.textContent = formatMs(metricMaximum(pointerMetrics.dragDurations));
  ui.pointerDiagCoalesced.textContent = String(pointerMetrics.coalesced);
  ui.pointerDiagState.textContent = [
    stale ? "无新指针事件" : pointerMetrics.currentState,
    "接收 " + pointerMetrics.received, "处理 " + pointerMetrics.processed,
    "捏合 " + pointerMetrics.pressTransitions + "/" + pointerMetrics.releaseTransitions,
    "拖拽 " + pointerMetrics.dragStarts + "/" + pointerMetrics.dragReleases,
    "中断 " + pointerMetrics.dragCancels,
  ].join(" · ");
}

function recordPointerReceived(event) {
  const now = performance.now();
  const pressed = Boolean(event?.pressed);
  const active = Boolean(event?.active);
  const rejected = event?.identity_confirmed === false;
  if (pointerMetrics.lastReceivedAt !== null) {
    const gap = now - pointerMetrics.lastReceivedAt;
    if (gap <= 1500) pushMetricSample(pointerMetrics.eventGaps, gap);
    else pointerMetrics.eventGaps = [];
  }
  if (pointerMetrics.lastReceivedPressed !== null && pressed !== pointerMetrics.lastReceivedPressed) {
    if (pressed) pointerMetrics.pressTransitions += 1;
    else pointerMetrics.releaseTransitions += 1;
  }
  if (pointerMetrics.lastReceivedActive === true && !active) pointerMetrics.dropouts += 1;
  if (!pointerMetrics.lastIdentityRejected && rejected) pointerMetrics.identityRejects += 1;
  pointerMetrics.lastReceivedAt = now;
  pointerMetrics.lastReceivedPressed = pressed;
  pointerMetrics.lastReceivedActive = active;
  pointerMetrics.lastIdentityRejected = rejected;
  pointerMetrics.received += 1;
  pushMetricSample(pointerMetrics.receivedTimes, now);
  pointerMetrics.eventHistory.push({
    at_ms: Math.round(now), active, pressed, identity_confirmed: !rejected,
    x: Number.isFinite(Number(event?.x)) ? Number(event.x) : null,
    y: Number.isFinite(Number(event?.y)) ? Number(event.y) : null,
  });
  if (pointerMetrics.eventHistory.length > 120) pointerMetrics.eventHistory.shift();
}

function recordPointerProcessed(startedAt, event) {
  pushMetricSample(pointerMetrics.processDurations, performance.now() - startedAt);
  pointerMetrics.processed += 1;
  pointerMetrics.currentState = !event?.active
    ? "指针已释放"
    : event.identity_confirmed === false
      ? "身份未确认"
      : event.pressed
        ? (pointerDragNodeId ? "节点拖拽中" : "捏合按下")
        : "光标移动中";
}

function recordPointerDragUpdate(durationMs) {
  pushMetricSample(pointerMetrics.dragDurations, durationMs);
}

function setPointerDiagnosticsOpen(open) {
  ui.pointerDiagnosticsPanel.hidden = !open;
  ui.pointerDiagnostics.setAttribute("aria-pressed", String(Boolean(open)));
  if (open) {
    updatePointerDiagnostics();
    if (pointerDiagnosticsTimer === null) pointerDiagnosticsTimer = window.setInterval(updatePointerDiagnostics, 250);
  } else if (pointerDiagnosticsTimer !== null) {
    window.clearInterval(pointerDiagnosticsTimer);
    pointerDiagnosticsTimer = null;
  }
}

function resetPointerDiagnostics() {
  for (const key of ["receivedTimes", "eventGaps", "rafWaits", "processDurations", "dragDurations", "eventHistory"]) {
    pointerMetrics[key] = [];
  }
  for (const key of [
    "received", "processed", "coalesced", "pressTransitions", "releaseTransitions",
    "dropouts", "identityRejects", "dragStarts", "dragReleases", "dragCancels",
  ]) pointerMetrics[key] = 0;
  pointerMetrics.lastReceivedAt = null;
  pointerMetrics.lastReceivedPressed = null;
  pointerMetrics.lastReceivedActive = null;
  pointerMetrics.lastIdentityRejected = false;
  pointerMetrics.lastRafScheduledAt = null;
  pointerMetrics.currentState = "统计已重置，等待指针事件";
  updatePointerDiagnostics();
}

async function exportPointerDiagnostics() {
  let settings = null;
  try { settings = await api("/api/pointer/settings"); } catch (_error) {}
  const rect = ui.canvasViewport.getBoundingClientRect();
  const payload = {
    exported_at: new Date().toISOString(), pointer_mode_enabled: pointerModeEnabled,
    mirror_x: pointerMirrorX, calibration_saved: Boolean(pointerCalibration), zoom,
    viewport: { width: Math.round(rect.width), height: Math.round(rect.height) },
    canvas: { width: ui.canvasWorld.clientWidth, height: ui.canvasWorld.clientHeight },
    node_count: workflow?.nodes.length || 0, edge_count: workflow?.edges.length || 0, settings,
    metrics: {
      received: pointerMetrics.received, processed: pointerMetrics.processed,
      coalesced_movement_samples: pointerMetrics.coalesced,
      press_transitions: pointerMetrics.pressTransitions, release_transitions: pointerMetrics.releaseTransitions,
      dropouts: pointerMetrics.dropouts, identity_rejections: pointerMetrics.identityRejects,
      drag_starts: pointerMetrics.dragStarts, drag_releases: pointerMetrics.dragReleases,
      drag_cancels: pointerMetrics.dragCancels,
      event_interval_p95_ms: metricPercentile(pointerMetrics.eventGaps, 0.95),
      raf_wait_p95_ms: metricPercentile(pointerMetrics.rafWaits, 0.95),
      processing_max_ms: metricMaximum(pointerMetrics.processDurations),
      node_update_max_ms: metricMaximum(pointerMetrics.dragDurations),
    },
    recent_events: pointerMetrics.eventHistory,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "pointer-diagnostics-" + new Date().toISOString().replace(/[:.]/g, "-") + ".json";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function loadPointerCalibration() {
  try {
    const saved = JSON.parse(localStorage.getItem(POINTER_CALIBRATION_KEY) || "null");
    if (saved?.mirrorX !== pointerMirrorX || !Array.isArray(saved?.matrix)
      || saved.matrix.length !== 8 || !saved.matrix.every(Number.isFinite)) return null;
    return saved;
  } catch (_error) {
    return null;
  }
}

function updatePointerCalibrationButton() {
  if (!ui.pointerCalibrate) return;
  const calibrating = Boolean(pointerCalibrationSession);
  const pointerAvailable = Boolean(pointerEventBuffer && window.PointerGeometry);
  ui.pointerCalibrate.disabled = !pointerAvailable || (!pointerModeEnabled && !calibrating);
  ui.pointerCalibrate.textContent = calibrating
    ? "取消校准"
    : pointerCalibration
      ? "重新校准"
      : "四角校准";
  ui.pointerCalibrate.dataset.state = pointerCalibration ? "calibrated" : "idle";
  ui.pointerCalibrate.title = calibrating
    ? "取消当前四角校准"
    : pointerCalibration
      ? "已完成四角校准；点击可重新采集"
      : "依次对准画布四角并捏合采集，校正摄像头透视偏差";
}

function setPointerModeUi(enabled) {
  pointerModeEnabled = Boolean(enabled);
  ui.pointerMode.textContent = pointerModeEnabled ? "手势拖拽：开启" : "手势拖拽：关闭";
  ui.pointerMode.setAttribute("aria-pressed", String(pointerModeEnabled));
  ui.pointerMode.dataset.state = pointerModeEnabled ? "active" : "idle";
  if (!pointerModeEnabled && pointerCalibrationSession) cancelPointerCalibration(false);
  updatePointerCalibrationButton();
}

function setPointerMirrorUi(enabled) {
  const next = Boolean(enabled);
  if (next !== pointerMirrorX) {
    pointerCalibration = null;
    try { localStorage.removeItem(POINTER_CALIBRATION_KEY); } catch (_error) {}
    if (pointerCalibrationSession) cancelPointerCalibration(false);
    setMessage("镜像方向已改变，原四角校准已失效；请重新校准", "ok");
  }
  pointerMirrorX = next;
  try { localStorage.setItem(POINTER_MIRROR_KEY, String(pointerMirrorX)); } catch (_error) {}
  ui.pointerMirror.textContent = pointerMirrorX ? "镜像：开启" : "镜像：关闭";
  ui.pointerMirror.setAttribute("aria-pressed", String(pointerMirrorX));
  updatePointerCalibrationButton();
}

async function refreshPointerMode() {
  const response = await api("/api/pointer/mode");
  const wasEnabled = pointerModeEnabled;
  setPointerModeUi(response.enabled);
  if (wasEnabled && !pointerModeEnabled) releaseHandPointer();
}

async function togglePointerMode() {
  ui.pointerMode.disabled = true;
  try {
    if (!pointerEventBuffer || !window.PointerGeometry) {
      setMessage("手势指针组件未加载；鼠标和键盘编辑仍然可用，请刷新页面或检查静态资源", "error");
      return;
    }
    if (!pointerModeEnabled) {
      const streamStatus = await api("/api/status");
      if (streamStatus.state !== "running") {
        setMessage("手势拖拽需要先启动摄像头视频流；鼠标和键盘编辑不受影响", "error");
        return;
      }
    }
    const response = await api("/api/pointer/mode", {
      method: "POST",
      body: JSON.stringify({ enabled: !pointerModeEnabled }),
    });
    setPointerModeUi(response.enabled);
    if (!response.enabled) releaseHandPointer();
    const controllerLocked = response.controller?.state === "locked";
    setMessage(response.enabled
      ? controllerLocked
        ? "手势拖拽已开启：伸出食指移动，捏合抓取节点，松开释放"
        : "手势拖拽已开启；请先在摄像头前完成 V 字主控锁定"
      : "手势拖拽已关闭");
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    ui.pointerMode.disabled = false;
  }
}

function renderPointerCalibrationOverlay() {
  const session = pointerCalibrationSession;
  if (!session) {
    pointerCalibrationOverlay.hidden = true;
    return;
  }
  const rect = ui.canvasViewport.getBoundingClientRect();
  pointerCalibrationOverlay.style.left = rect.left + "px";
  pointerCalibrationOverlay.style.top = rect.top + "px";
  pointerCalibrationOverlay.style.width = rect.width + "px";
  pointerCalibrationOverlay.style.height = rect.height + "px";
  const target = POINTER_CALIBRATION_TARGETS[session.index];
  pointerCalibrationTarget.style.left = target.x * 100 + "%";
  pointerCalibrationTarget.style.top = target.y * 100 + "%";
  pointerCalibrationHint.textContent = session.awaitingRelease
    ? "已采集 " + session.points.length + "/4 · 松开捏合后继续"
    : "请将光标对准" + target.label + "角圆点并捏合确认 · " + (session.index + 1) + "/4";
  pointerCalibrationOverlay.hidden = false;
}

function startPointerCalibration() {
  if (pointerCalibrationSession) {
    cancelPointerCalibration(true);
    return;
  }
  if (!pointerModeEnabled) {
    setMessage("请先开启手势拖拽，再进行四角校准", "error");
    return;
  }
  pointerCalibrationSession = {
    points: [],
    index: 0,
    awaitingRelease: lastPointerPressed,
  };
  pointerPressed = lastPointerPressed;
  pointerDownTarget = null;
  pointerDragNodeId = null;
  pointerGrabOffset = null;
  pointerDownPoint = null;
  pointerMoved = false;
  pointerIgnoreUntilRelease = false;
  renderPointerCalibrationOverlay();
  updatePointerCalibrationButton();
  setMessage("四角校准已开始：依次对准画布左上、右上、右下、左下圆点，每处捏合一次");
}

function cancelPointerCalibration(showMessage = true) {
  if (!pointerCalibrationSession) return;
  pointerCalibrationSession = null;
  pointerIgnoreUntilRelease = lastPointerPressed;
  pointerPressed = lastPointerPressed;
  pointerCalibrationOverlay.hidden = true;
  updatePointerCalibrationButton();
  if (showMessage) setMessage("已取消四角校准");
}

function capturePointerCalibrationPoint(event) {
  const session = pointerCalibrationSession;
  if (!session) return;
  const x = Number(event.x);
  const y = Number(event.y);
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > 1 || y < 0 || y > 1) {
    cancelPointerCalibration(false);
    setMessage("校准坐标无效，请重新开始", "error");
    return;
  }
  session.points.push({ x: pointerMirrorX ? 1 - x : x, y });
  session.index += 1;
  if (session.index < POINTER_CALIBRATION_TARGETS.length) {
    session.awaitingRelease = true;
    renderPointerCalibrationOverlay();
    return;
  }
  try {
    const matrix = PointerGeometry.solveHomography(
      session.points,
      POINTER_CALIBRATION_TARGETS.map(({ x: targetX, y: targetY }) => ({ x: targetX, y: targetY })),
    );
    pointerCalibration = { matrix, mirrorX: pointerMirrorX, savedAt: new Date().toISOString() };
    try { localStorage.setItem(POINTER_CALIBRATION_KEY, JSON.stringify(pointerCalibration)); } catch (_error) {}
    pointerCalibrationSession = null;
    pointerCalibrationOverlay.hidden = true;
    updatePointerCalibrationButton();
    setMessage("四角校准完成，已保存；现在可以准确抓取节点", "ok");
  } catch (error) {
    pointerCalibrationSession = null;
    pointerCalibrationOverlay.hidden = true;
    updatePointerCalibrationButton();
    setMessage(error.message || "四角校准失败，请重新采集", "error");
  }
}

function pointerClientPoint(event, useCalibration = true) {
  const rect = ui.canvasViewport.getBoundingClientRect();
  const matrix = useCalibration && pointerCalibration?.mirrorX === pointerMirrorX
    ? pointerCalibration.matrix
    : null;
  return PointerGeometry.normalizedToClient(
    { x: Number(event.x), y: Number(event.y) },
    rect,
    pointerMirrorX,
    matrix,
  );
}

function clientToWorld(clientX, clientY) {
  const rect = ui.canvasViewport.getBoundingClientRect();
  if (window.PointerGeometry?.clientToWorld) {
    return PointerGeometry.clientToWorld(
      { x: clientX, y: clientY },
      rect,
      ui.canvasViewport.scrollLeft,
      ui.canvasViewport.scrollTop,
      zoom,
    );
  }
  return {
    x: (clientX - rect.left + ui.canvasViewport.scrollLeft) / zoom,
    y: (clientY - rect.top + ui.canvasViewport.scrollTop) / zoom,
  };
}

function releaseHandPointer() {
  if (pointerAnimationFrame !== null) {
    window.cancelAnimationFrame(pointerAnimationFrame);
    pointerAnimationFrame = null;
  }
  pointerEventBuffer?.clear();
  pointerMetrics.lastRafScheduledAt = null;
  if (pointerDragNodeId) pointerMetrics.dragCancels += 1;
  if (pointerDragNodeId && pointerMoved && pointerHistoryBefore) pushGraphHistory(pointerHistoryBefore);
  pointerHistoryBefore = null;
  pointerPressed = lastPointerPressed;
  pointerDownTarget = null;
  pointerDragNodeId = null;
  pointerDownPoint = null;
  pointerGrabOffset = null;
  pointerMoved = false;
  handPointerCursor.hidden = true;
  handPointerCursor.dataset.pressed = "false";
}

function beginHandPointerPress(clientX, clientY) {
  pointerDownPoint = { x: clientX, y: clientY };
  pointerMoved = false;
  const target = document.elementFromPoint(clientX, clientY);
  const nodeCard = target?.closest(".canvas-node");
  if (nodeCard) {
    const nodeId = nodeCard.dataset.nodeId;
    if (ui.linkMode.getAttribute("aria-pressed") === "true") {
      selectOrLink(nodeId);
      pointerDownTarget = null;
      return;
    }
    const node = findNode(nodeId);
    if (!node) return;
    pointerHistoryBefore = graphSnapshot();
    selectedNodeId = nodeId;
    selectedEdgeKey = null;
    updateNodeSelectionState();
    renderInspector();
    const worldPoint = clientToWorld(clientX, clientY);
    pointerGrabOffset = {
      x: worldPoint.x - node.position.x,
      y: worldPoint.y - node.position.y,
    };
    pointerDragNodeId = nodeId;
    pointerMetrics.dragStarts += 1;
    pointerDownTarget = null;
    return;
  }
  pointerDownTarget = target;
}

function moveHandPointerPress(clientX, clientY) {
  if (!pointerPressed || !pointerDownPoint) return;
  const distance = Math.hypot(clientX - pointerDownPoint.x, clientY - pointerDownPoint.y);
  if (distance >= 5) pointerMoved = true;
  if (pointerDragNodeId && pointerMoved) {
    moveNode(pointerDragNodeId, clientX, clientY, pointerGrabOffset);
  }
}

function endHandPointerPress() {
  if (pointerDragNodeId) pointerMetrics.dragReleases += 1;
  if (pointerDragNodeId && pointerMoved && pointerHistoryBefore) pushGraphHistory(pointerHistoryBefore);
  pointerHistoryBefore = null;
  if (!pointerMoved && !pointerDragNodeId && pointerDownTarget instanceof Element) {
    const target = pointerDownTarget.closest("button, a, [role='button'], input, select, textarea") || pointerDownTarget;
    if (!target.matches(":disabled")) {
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) {
        target.focus();
      }
      target.click();
    }
  }
  pointerPressed = false;
  pointerDownTarget = null;
  pointerDragNodeId = null;
  pointerDownPoint = null;
  pointerGrabOffset = null;
  pointerMoved = false;
  handPointerCursor.dataset.pressed = "false";
}

function processHandPointerEvent(event) {
  lastPointerPressed = Boolean(event?.pressed);
  if (!pointerModeEnabled) return;
  if (!event?.active || event.identity_confirmed === false
    || !Number.isFinite(Number(event.x)) || !Number.isFinite(Number(event.y))) {
    if (pointerCalibrationSession) cancelPointerCalibration(false);
    releaseHandPointer();
    return;
  }
  const point = pointerClientPoint(event, !pointerCalibrationSession);
  handPointerCursor.hidden = false;
  handPointerCursor.style.left = point.x + "px";
  handPointerCursor.style.top = point.y + "px";
  handPointerCursor.dataset.pressed = String(Boolean(event.pressed));

  if (pointerCalibrationSession) {
    const session = pointerCalibrationSession;
    if (session.awaitingRelease) {
      if (!event.pressed) {
        session.awaitingRelease = false;
        pointerPressed = false;
        renderPointerCalibrationOverlay();
      }
      return;
    }
    if (event.pressed && !pointerPressed) {
      pointerPressed = true;
      session.awaitingRelease = true;
      capturePointerCalibrationPoint(event);
      renderPointerCalibrationOverlay();
    } else if (!event.pressed) {
      pointerPressed = false;
    }
    return;
  }

  if (pointerIgnoreUntilRelease) {
    if (!event.pressed) {
      pointerIgnoreUntilRelease = false;
      pointerPressed = false;
    }
    return;
  }
  if (event.pressed && !pointerPressed) {
    pointerPressed = true;
    beginHandPointerPress(point.x, point.y);
  } else if (event.pressed && pointerPressed) {
    moveHandPointerPress(point.x, point.y);
  } else if (!event.pressed && pointerPressed) {
    // The release sample is also the final drag coordinate; apply it before committing the drop.
    moveHandPointerPress(point.x, point.y);
    endHandPointerPress();
  }
}

function processHandPointer(event) {
  const startedAt = performance.now();
  try {
    processHandPointerEvent(event);
  } finally {
    recordPointerProcessed(startedAt, event);
  }
}

function handleHandPointer(event) {
  if (!pointerEventBuffer || !event || typeof event !== "object") return;
  lastPointerPressed = Boolean(event.pressed);
  recordPointerReceived(event);
  pointerEventBuffer.push(event);
  if (pointerAnimationFrame !== null) return;
  pointerMetrics.lastRafScheduledAt = performance.now();
  pointerAnimationFrame = window.requestAnimationFrame(() => {
    pointerAnimationFrame = null;
    if (pointerMetrics.lastRafScheduledAt !== null) {
      pushMetricSample(pointerMetrics.rafWaits, performance.now() - pointerMetrics.lastRafScheduledAt);
    }
    pointerMetrics.lastRafScheduledAt = null;
    const batch = pointerEventBuffer.drain();
    pointerMetrics.coalesced += batch.coalesced;
    for (const pending of batch.events) processHandPointer(pending);
  });
}

function graphSnapshot() {
  return workflow ? WorkflowGraph.snapshot(workflow) : null;
}

function pushGraphHistory(before) {
  if (!before) return;
  graphHistory.pushSnapshot(before);
  refreshHistoryButtons();
}

function refreshHistoryButtons() {
  if (!ui.undoWorkflow || !ui.redoWorkflow) return;
  ui.undoWorkflow.disabled = !workflow || !graphHistory.canUndo;
  ui.redoWorkflow.disabled = !workflow || !graphHistory.canRedo;
}

function restoreGraphHistory(state, message) {
  if (!workflow || !state) return;
  WorkflowGraph.restore(workflow, state);
  selectedNodeId = null;
  selectedEdgeKey = null;
  linkSourceId = null;
  linkHistoryBefore = null;
  renderTrigger();
  renderCanvas();
  renderInspector();
  refreshHistoryButtons();
  setMessage(message);
}

function undoGraphEdit() {
  if (!workflow) return;
  const state = graphHistory.undo(workflow);
  if (state) restoreGraphHistory(state, "已撤销上一步编辑");
}

function redoGraphEdit() {
  if (!workflow) return;
  const state = graphHistory.redo(workflow);
  if (state) restoreGraphHistory(state, "已恢复下一步编辑");
}

function commitGraphMutation(mutator, message) {
  if (!workflow) return false;
  const before = graphSnapshot();
  mutator();
  pushGraphHistory(before);
  if (message) setMessage(message);
  return true;
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
  refreshHistoryButtons();
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
  selectedEdgeKey = null;
  linkSourceId = null;
  linkHistoryBefore = null;
  propertyHistoryBefore = null;
  graphHistory.clear();
  refreshHistoryButtons();
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

function addNode(node, options = {}) {
  if (!workflow) return;
  const before = graphSnapshot();

  if (node.type === "end") {
    const result = WorkflowGraph.addEndNode(
      workflow, node, selectedNodeId, ui.edgeWhen.value || undefined,
    );
    if (!result.ok) {
      setMessage(result.error, "error");
      return;
    }
    applyGraphResult(result, before, "结束节点已添加");
    return;
  }

  const resolution = WorkflowGraph.resolveInsertEdge(workflow, {
    selectedNodeId,
    selectedEdgeKey: options.edgeKey || selectedEdgeKey,
  });
  if (!resolution.ok) {
    highlightInsertEdges(resolution.candidates || []);
    const messages = {
      "multiple-terminal-paths": "当前有多个结束分支，请点击目标连线上的 +，再选择要添加的节点",
      "selected-node-has-branches": "所选节点有多个出口，请点击要插入的分支连线上的 +",
      "selected-node-has-no-output": "所选节点没有可插入的后继路径，请先连接该节点",
      "selected-edge-missing": "所选连线已变化，请重新选择",
      "end-has-multiple-incoming": "该结束节点有多个入口，请选择具体连线",
    };
    setMessage(messages[resolution.reason] || "无法确定插入位置，请先选择一个节点或连线", "error");
    return;
  }

  const result = WorkflowGraph.insertNodeAtEdge(workflow, node, resolution.edge, {
    position: options.position,
  });
  if (!result.ok) {
    setMessage(result.error, "error");
    return;
  }
  const message = node.type === "condition"
    ? "条件节点已插入：true 继续原流程，false 默认结束；可继续在任一分支连线上添加节点"
    : "节点已插入，原有执行路径已自动接续";
  applyGraphResult(result, before, message);
}

function applyGraphResult(result, before, message) {
  if (!result || !result.ok) {
    setMessage(result?.error || "图操作失败", "error");
    return false;
  }
  workflow.nodes = result.nodes;
  workflow.edges = result.edges;
  selectedNodeId = result.selectedNodeId || null;
  selectedEdgeKey = null;
  linkSourceId = null;
  linkHistoryBefore = null;
  ui.linkMode.setAttribute("aria-pressed", "false");
  pushGraphHistory(before);
  renderCanvas();
  renderInspector();
  clearInsertEdgeHighlights();
  if (message) setMessage(message);
  return true;
}

function highlightInsertEdges(edges) {
  const keys = new Set(edges.map((edge) => WorkflowGraph.edgeKey(edge)));
  for (const [key, record] of edgeRecords) {
    record.group.dataset.candidate = String(keys.has(key));
  }
}

function clearInsertEdgeHighlights() {
  for (const record of edgeRecords.values()) delete record.group.dataset.candidate;
}

function selectEdge(key) {
  if (!workflow || !edgeRecords.has(key)) return;
  selectedEdgeKey = key;
  selectedNodeId = null;
  linkSourceId = null;
  updateNodeSelectionState();
  renderInspector();
  const record = edgeRecords.get(key);
  const label = record.edge.when || "常规";
  setMessage("已选中 " + label + " 执行路径；现在点击左侧节点即可插入到这条连线上");
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
    select.addEventListener("change", () => { const before = graphSnapshot(); trigger.gesture = select.value; pushGraphHistory(before); renderCanvas(); });
    ui.triggerFields.append(select);
  } else if (trigger.type === "gesture_sequence_trigger") {
    const input = make("input");
    input.type = "text";
    input.value = trigger.gestures.join(",");
    input.placeholder = "Open_Palm,Victory";
    input.setAttribute("aria-label", "手势序列，以逗号分隔");
    input.addEventListener("change", () => { const before = graphSnapshot(); trigger.gestures = input.value.split(",").map((value) => value.trim()).filter(Boolean); pushGraphHistory(before); renderCanvas(); });
    const windowInput = make("input");
    windowInput.type = "number";
    windowInput.min = "1000";
    windowInput.max = "30000";
    windowInput.step = "500";
    windowInput.value = String(trigger.sequence_window_ms || 5000);
    windowInput.setAttribute("aria-label", "序列时间窗口毫秒");
    windowInput.addEventListener("change", () => { const before = graphSnapshot(); trigger.sequence_window_ms = Number(windowInput.value); pushGraphHistory(before); });
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

function updateCanvasBounds() {
  const nodes = workflow?.nodes || [];
  const maxX = Math.max(170, ...nodes.map((node) => (node.position?.x ?? 170) + 236));
  const maxY = Math.max(180, ...nodes.map((node) => (node.position?.y ?? 180) + 150));
  const width = Math.max(1900, Math.ceil(maxX + 180));
  const height = Math.max(1100, Math.ceil(maxY + 180));
  ui.canvasWorld.style.width = width + "px";
  ui.canvasWorld.style.height = height + "px";
  ui.edgeLayer.setAttribute("width", String(width));
  ui.edgeLayer.setAttribute("height", String(height));
  ui.edgeLayer.style.width = width + "px";
  ui.edgeLayer.style.height = height + "px";
}

function renderCanvas() {
  nodeCardsById.clear();
  nodeModelsById.clear();
  if (!workflow) {
    ui.canvasNodes.replaceChildren();
    updateCanvasBounds();
    drawEdges();
    return;
  }
  ui.canvasNodes.replaceChildren();
  for (const node of workflow.nodes) {
    nodeModelsById.set(node.id, node);
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
      mouseHistoryBefore = graphSnapshot();
      const worldPoint = clientToWorld(event.clientX, event.clientY);
      mouseDragOffset = {
        x: worldPoint.x - node.position.x,
        y: worldPoint.y - node.position.y,
      };
      event.dataTransfer.setData("text/plain", "node:" + node.id);
      event.dataTransfer.effectAllowed = "move";
    });
    card.addEventListener("dragend", () => { mouseDragOffset = null; mouseHistoryBefore = null; });
    nodeCardsById.set(node.id, card);
    ui.canvasNodes.append(card);
  }
  updateCanvasBounds();
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

function indexEdgeForNode(nodeId, key) {
  if (!nodeId || nodeId === "trigger") return;
  if (!edgeKeysByNode.has(nodeId)) edgeKeysByNode.set(nodeId, new Set());
  edgeKeysByNode.get(nodeId).add(key);
}

function updateEdgeRecord(record) {
  const source = record.sourceId === "trigger" ? null : nodeModelsById.get(record.sourceId);
  const target = nodeModelsById.get(record.targetId);
  if (!target || (record.sourceId !== "trigger" && !source)) return;
  const x1 = source ? source.position.x + 236 : 132;
  const y1 = source ? source.position.y + 53 : 130;
  const x2 = target.position.x;
  const y2 = target.position.y + 53;
  const bend = Math.max(38, (x2 - x1) / 2);
  const pathData = "M " + x1 + " " + y1 + " C " + (x1 + bend) + " " + y1 + ", " + (x2 - bend) + " " + y2 + ", " + x2 + " " + y2;
  record.path.setAttribute("d", pathData);
  record.hitPath.setAttribute("d", pathData);
  if (record.labelElement) {
    record.labelElement.setAttribute("x", String((x1 + x2) / 2));
    record.labelElement.setAttribute("y", String((y1 + y2) / 2 - 7));
  }
  const t = 0.5;
  const mt = 1 - t;
  const c1x = x1 + bend;
  const c2x = x2 - bend;
  const midX = mt * mt * mt * x1 + 3 * mt * mt * t * c1x + 3 * mt * t * t * c2x + t * t * t * x2;
  const midY = mt * mt * mt * y1 + 3 * mt * mt * t * y1 + 3 * mt * t * t * y2 + t * t * t * y2;
  record.insertButton.setAttribute("transform", "translate(" + midX + " " + midY + ")");
  record.group.dataset.selected = String(record.key === selectedEdgeKey);
}

function addEdgeRecord(svg, key, edge, styleKey, label) {
  const namespace = "http://www.w3.org/2000/svg";
  const group = document.createElementNS(namespace, "g");
  group.classList.add("edge-group");
  group.dataset.edgeKey = key;
  group.dataset.selected = String(key === selectedEdgeKey);
  group.setAttribute("role", "button");
  group.setAttribute("tabindex", "0");
  group.setAttribute("aria-label", "选择" + (label || "常规") + "执行连线");

  const hitPath = document.createElementNS(namespace, "path");
  hitPath.classList.add("edge-hit-area");
  const path = document.createElementNS(namespace, "path");
  path.classList.add("edge-path");
  if (styleKey === "error") path.classList.add("edge-error");
  group.append(hitPath, path);

  let labelElement = null;
  if (label) {
    labelElement = document.createElementNS(namespace, "text");
    labelElement.classList.add("edge-label");
    labelElement.textContent = label;
    group.append(labelElement);
  }

  const insertButton = document.createElementNS(namespace, "g");
  insertButton.classList.add("edge-insert-button");
  insertButton.dataset.edgeKey = key;
  insertButton.setAttribute("role", "button");
  insertButton.setAttribute("tabindex", "0");
  insertButton.setAttribute("aria-label", "选择此连线作为节点插入位置");
  const circle = document.createElementNS(namespace, "circle");
  circle.setAttribute("r", "10");
  const plus = document.createElementNS(namespace, "text");
  plus.setAttribute("x", "0");
  plus.setAttribute("y", "4");
  plus.setAttribute("text-anchor", "middle");
  plus.textContent = "+";
  insertButton.append(circle, plus);
  group.append(insertButton);

  const choose = (event) => {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    selectEdge(key);
  };
  hitPath.addEventListener("click", choose);
  group.addEventListener("click", (event) => {
    if (event.target === group) choose(event);
  });
  insertButton.addEventListener("click", choose);
  for (const element of [group, insertButton]) {
    element.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") choose(event);
    });
  }

  svg.append(group);
  const record = {
    key, edge: { source: edge.source, target: edge.target, when: edge.when, virtual: edge.virtual === true },
    sourceId: edge.source, targetId: edge.target, group, hitPath, path, labelElement, insertButton,
  };
  edgeRecords.set(key, record);
  indexEdgeForNode(edge.source, key);
  indexEdgeForNode(edge.target, key);
  updateEdgeRecord(record);
}

function drawEdges() {
  const svg = ui.edgeLayer;
  svg.querySelectorAll(".edge-group").forEach((element) => element.remove());
  edgeRecords.clear();
  edgeKeysByNode.clear();
  if (!workflow) return;
  const root = workflow.nodes.find((node) => !workflow.edges.some((edge) => edge.target === node.id));
  if (root) {
    const virtual = { source: "trigger", target: root.id, virtual: true };
    addEdgeRecord(svg, WorkflowGraph.edgeKey(virtual), virtual, "trigger", "");
  }
  workflow.edges.forEach((edge) => {
    const key = WorkflowGraph.edgeKey(edge);
    addEdgeRecord(svg, key, edge, edge.when === "error" ? "error" : edge.source, edge.when || "");
  });
}

function distanceToSegment(point, start, end) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSquared = dx * dx + dy * dy;
  if (!lengthSquared) return Math.hypot(point.x - start.x, point.y - start.y);
  const t = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared));
  return Math.hypot(point.x - (start.x + t * dx), point.y - (start.y + t * dy));
}

function findNearestEdgeKey(clientX, clientY) {
  const point = clientToWorld(clientX, clientY);
  let nearestKey = null;
  let nearestDistance = 24 / zoom;
  for (const record of edgeRecords.values()) {
    const source = record.sourceId === "trigger" ? null : findNode(record.sourceId);
    const target = findNode(record.targetId);
    if (!target) continue;
    const x1 = source ? source.position.x + 236 : 132;
    const y1 = source ? source.position.y + 53 : 130;
    const x2 = target.position.x;
    const y2 = target.position.y + 53;
    const bend = Math.max(38, (x2 - x1) / 2);
    const c1 = { x: x1 + bend, y: y1 };
    const c2 = { x: x2 - bend, y: y2 };
    let previous = { x: x1, y: y1 };
    for (let step = 1; step <= 24; step += 1) {
      const t = step / 24;
      const mt = 1 - t;
      const current = {
        x: mt * mt * mt * x1 + 3 * mt * mt * t * c1.x + 3 * mt * t * t * c2.x + t * t * t * x2,
        y: mt * mt * mt * y1 + 3 * mt * mt * t * c1.y + 3 * mt * t * t * c2.y + t * t * t * y2,
      };
      const distance = distanceToSegment(point, previous, current);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestKey = record.key;
      }
      previous = current;
    }
  }
  return nearestKey;
}

function drawEdgesForNode(nodeId) {
  for (const key of edgeKeysByNode.get(nodeId) || []) {
    const record = edgeRecords.get(key);
    if (record) updateEdgeRecord(record);
  }
}

function updateNodeSelectionState() {
  for (const card of ui.canvasNodes.children) {
    card.dataset.selected = String(card.dataset.nodeId === selectedNodeId);
    card.dataset.linkSource = String(card.dataset.nodeId === linkSourceId);
  }
  for (const record of edgeRecords.values()) {
    record.group.dataset.selected = String(record.key === selectedEdgeKey);
  }
}

function updateConnectionOptions(sourceId) {
  const source = findNode(sourceId);
  let options = [["", "常规"]];
  if (source?.type === "condition") options = [["true", "true"], ["false", "false"]];
  else if (source?.type === "action" && source.on_error === "branch") options = [["", "常规"], ["error", "error"]];
  ui.edgeWhen.replaceChildren();
  for (const [value, label] of options) {
    const option = make("option", "", label);
    option.value = value;
    ui.edgeWhen.append(option);
  }
  if (!options.some(([value]) => value === ui.edgeWhen.value)) ui.edgeWhen.value = options[0][0];
}

function selectOrLink(nodeId) {
  if (ui.linkMode.getAttribute("aria-pressed") === "true") {
    if (!linkSourceId) {
      linkSourceId = nodeId;
      selectedNodeId = nodeId;
      selectedEdgeKey = null;
      linkHistoryBefore = graphSnapshot();
      updateConnectionOptions(nodeId);
      setMessage("已选择连线起点；请选择出口类型，再选择目标节点");
    } else if (linkSourceId !== nodeId) {
      const result = WorkflowGraph.connectNodes(workflow, linkSourceId, nodeId, ui.edgeWhen.value || undefined);
      if (!result.ok) {
        setMessage(result.error, "error");
        return;
      }
      const before = linkHistoryBefore || graphSnapshot();
      applyGraphResult(result, before, "连线已创建，请校验工作流");
      ui.linkMode.setAttribute("aria-pressed", "false");
    }
    updateNodeSelectionState();
    return;
  }
  selectedNodeId = nodeId;
  selectedEdgeKey = null;
  linkSourceId = null;
  clearInsertEdgeHighlights();
  updateNodeSelectionState();
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
  const begin = () => {
    if (!propertyHistoryBefore) propertyHistoryBefore = graphSnapshot();
  };
  const apply = () => {
    if (!workflow) return;
    begin();
    update(control.type === "checkbox" ? control.checked : control.type === "number" ? Number(control.value) : control.value);
    renderCanvas();
  };
  const commit = () => {
    if (!propertyHistoryBefore) return;
    pushGraphHistory(propertyHistoryBefore);
    propertyHistoryBefore = null;
  };
  control.addEventListener("focus", begin);
  control.addEventListener("input", apply);
  control.addEventListener("change", () => { apply(); commit(); });
  control.addEventListener("blur", commit);
}

function renderInspector() {
  ui.inspectorContent.replaceChildren();
  const node = currentNode();
  ui.duplicateNode.disabled = !node || !WorkflowGraph.canDuplicateNode(workflow, node.id).ok;
  ui.deleteNode.disabled = !node || !WorkflowGraph.canDeleteNode(workflow, node.id).ok;
  if (!node) {
    if (selectedEdgeKey) {
      const selectedEdge = edgeRecords.get(selectedEdgeKey)?.edge;
      ui.inspectorContent.append(make("p", "muted", "已选择 " + (selectedEdge?.when || "常规") + " 执行连线。点击左侧节点可插入；按 Delete 可断开连线。"));
    } else {
      ui.inspectorContent.append(make("p", "muted", "选择画布节点或执行连线"));
    }
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
    errorPath.addEventListener("change", () => {
      const before = graphSnapshot();
      const result = WorkflowGraph.setActionErrorPolicy(workflow, node.id, errorPath.value);
      if (!result.ok) {
        setMessage(result.error, "error");
        renderInspector();
        return;
      }
      applyGraphResult(result, before, errorPath.value === "branch" ? "已创建错误分支和默认结束节点" : "失败策略已更新");
    });
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
    const before = graphSnapshot();
    node.action = select.value;
    node.params = {};
    const schema = actionDefinitions.find((item) => item.name === node.action)?.schema;
    for (const name of schema?.required || []) {
      const rule = schema.properties[name];
      node.params[name] = rule.enum?.[0] ?? rule.minimum ?? (rule.type === "boolean" ? false : "");
    }
    pushGraphHistory(before);
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
        const label = rule.enum_labels?.[choice];
        const option = make("option", "", label ? label + "（" + choice + "）" : String(choice));
        option.value = String(choice);
        control.append(option);
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

function moveNode(nodeId, clientX, clientY, grabOffset = null) {
  const startedAt = performance.now();
  const node = nodeModelsById.get(nodeId) || findNode(nodeId);
  if (!node) return;
  const card = nodeCardsById.get(nodeId);
  const worldPoint = clientToWorld(clientX, clientY);
  const offset = grabOffset || {
    x: (card?.offsetWidth || 236) / 2,
    y: (card?.offsetHeight || 106) / 2,
  };
  node.position = window.PointerGeometry?.nodePositionFromPointer
    ? PointerGeometry.nodePositionFromPointer(
      worldPoint,
      offset,
      { width: ui.canvasWorld.clientWidth, height: ui.canvasWorld.clientHeight },
      { width: card?.offsetWidth || 236, height: card?.offsetHeight || 106 },
    )
    : {
      x: Math.max(0, Math.min(5000, Math.round(worldPoint.x - offset.x))),
      y: Math.max(0, Math.min(5000, Math.round(worldPoint.y - offset.y))),
    };
  if (card) {
    card.style.left = node.position.x + "px";
    card.style.top = node.position.y + "px";
  }
  drawEdgesForNode(nodeId);
  recordPointerDragUpdate(performance.now() - startedAt);
}

function autoArrange() {
  if (!workflow) return;
  const before = graphSnapshot();
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
  pushGraphHistory(before);
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
      if (event.type === "pointer") {
        handleHandPointer(event);
        return;
      }
      if (event.type === "controller" && ["unlocked", "reacquiring"].includes(event.state)) {
        if (pointerCalibrationSession) cancelPointerCalibration(false);
        releaseHandPointer();
      }
      if (event.type === "stream" && event.state !== "running") {
        if (pointerCalibrationSession) cancelPointerCalibration(false);
        releaseHandPointer();
      }
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
  if (!node) return;
  const before = graphSnapshot();
  const result = WorkflowGraph.duplicateNode(workflow, node.id);
  if (!result.ok) {
    setMessage(result.error, "error");
    return;
  }
  applyGraphResult(result, before, "节点已复制并插入原节点之后");
}

function deleteNode() {
  const node = currentNode();
  if (!node) return;
  const before = graphSnapshot();
  const result = WorkflowGraph.removeNode(workflow, node.id);
  if (!result.ok) {
    setMessage(result.error, "error");
    return;
  }
  applyGraphResult(result, before, "节点已删除，前后路径已自动接续");
}

function deleteSelectedEdge() {
  if (!selectedEdgeKey) return;
  const before = graphSnapshot();
  const result = WorkflowGraph.removeEdge(workflow, selectedEdgeKey);
  if (!result.ok) {
    setMessage(result.error, "error");
    return;
  }
  applyGraphResult(result, before, "连线已断开；请重新连接对应出口后再保存");
}

async function initialize() {
  const errors = [];
  const pointerAvailable = Boolean(pointerEventBuffer && window.PointerGeometry);
  ui.pointerMode.disabled = !pointerAvailable;
  if (!pointerAvailable) {
    ui.pointerMode.title = "手势指针组件未加载；鼠标和键盘编辑仍然可用";
    ui.pointerCalibrate.disabled = true;
  }

  // Load the action catalogue and saved workflows independently. A failure in
  // one optional panel must not leave the whole editor in its static loading state.
  const [actionResult, workflowResult] = await Promise.allSettled([
    api("/api/actions"),
    api("/api/workflows"),
  ]);

  if (actionResult.status === "fulfilled" && Array.isArray(actionResult.value.actions)) {
    actionDefinitions = actionResult.value.actions;
    renderActionLibrary();
  } else {
    actionDefinitions = [];
    renderActionLibrary();
    ui.actionLibrary.append(make("p", "muted", "动作加载失败；请检查服务连接后刷新"));
    errors.push("动作列表加载失败：" + (actionResult.reason?.message || "响应格式无效"));
  }

  if (workflowResult.status === "fulfilled" && Array.isArray(workflowResult.value.workflows)) {
    workflows = workflowResult.value.workflows;
    renderWorkflowOptions();
    if (workflows.length) {
      try {
        await loadWorkflow(workflows[0].id);
      } catch (error) {
        errors.push("工作流载入失败：" + error.message);
        setEditingEnabled(Boolean(workflow));
        renderCanvas();
      }
    } else {
      setEditingEnabled(false);
      renderCanvas();
    }
  } else {
    workflows = [];
    renderWorkflowOptions();
    setEditingEnabled(false);
    renderCanvas();
    errors.push("工作流列表加载失败：" + (workflowResult.reason?.message || "响应格式无效"));
  }

  const [runsResult, displayResult] = await Promise.allSettled([
    refreshRuns(),
    refreshDisplayStatus(),
  ]);
  if (runsResult.status === "rejected") errors.push("运行记录加载失败：" + runsResult.reason.message);
  if (displayResult.status === "rejected") errors.push("展示页面状态读取失败：" + displayResult.reason.message);
  if (!pointerAvailable) errors.push("手势指针模块未加载；鼠标和键盘编辑不受影响");
  if (errors.length) setMessage(errors.join("；"), "error");
}

ui.newWorkflow.addEventListener("click", () => createWorkflow().catch((error) => setMessage(error.message, "error")));
ui.copyWorkflow.addEventListener("click", () => duplicateWorkflow().catch((error) => setMessage(error.message, "error")));
ui.deleteWorkflow.addEventListener("click", () => deleteWorkflow().catch((error) => setMessage(error.message, "error")));
ui.saveWorkflow.addEventListener("click", () => saveWorkflow().catch((error) => setMessage(error.message, "error")));
ui.validateWorkflow.addEventListener("click", () => validateCurrent().catch((error) => setMessage(error.message, "error")));
ui.dryRunWorkflow.addEventListener("click", () => dryRun().catch((error) => setMessage(error.message, "error")));
ui.undoWorkflow.addEventListener("click", undoGraphEdit);
ui.redoWorkflow.addEventListener("click", redoGraphEdit);
ui.toggleWorkflow.addEventListener("click", () => toggleWorkflow().catch((error) => setMessage(error.message, "error")));
ui.workflowSelect.addEventListener("change", () => loadWorkflow(ui.workflowSelect.value).catch((error) => setMessage(error.message, "error")));
ui.workflowName.addEventListener("input", updateHeaderData);
ui.workflowDescription.addEventListener("input", updateHeaderData);
ui.triggerType.addEventListener("change", () => {
  if (!workflow) return;
  const before = graphSnapshot();
  const type = ui.triggerType.value;
  workflow.trigger = type === "gesture_trigger" ? { type, gesture: "Open_Palm" }
    : type === "gesture_sequence_trigger" ? { type, gestures: ["Open_Palm", "Victory"], sequence_window_ms: 5000 }
      : { type };
  pushGraphHistory(before);
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
  selectedEdgeKey = null;
  graphHistory.clear();
  refreshHistoryButtons();
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
  linkHistoryBefore = null;
  if (active) setMessage("选择起点，再选择目标节点；条件节点可选择 true/false，错误分支动作可选择 error");
  else { clearMessage(); updateConnectionOptions(null); }
  renderCanvas();
});
ui.autoArrange.addEventListener("click", autoArrange);
ui.zoomIn.addEventListener("click", () => { zoom = Math.min(1.5, zoom + 0.1); updateZoom(); });
ui.zoomOut.addEventListener("click", () => { zoom = Math.max(0.6, zoom - 0.1); updateZoom(); });
ui.duplicateNode.addEventListener("click", duplicateNode);
ui.deleteNode.addEventListener("click", deleteNode);
ui.pointerMode.addEventListener("click", () => togglePointerMode());
ui.pointerMirror.addEventListener("click", () => setPointerMirrorUi(!pointerMirrorX));
ui.pointerCalibrate.addEventListener("click", startPointerCalibration);
ui.pointerDiagnostics.addEventListener("click", () => setPointerDiagnosticsOpen(ui.pointerDiagnosticsPanel.hidden));
ui.pointerDiagnosticsClose.addEventListener("click", () => setPointerDiagnosticsOpen(false));
ui.pointerDiagnosticsReset.addEventListener("click", resetPointerDiagnostics);
ui.pointerDiagnosticsExport.addEventListener("click", () => exportPointerDiagnostics().catch((error) => setMessage(error.message, "error")));
document.addEventListener("keydown", (event) => {
  const target = event.target;
  const editing = target instanceof Element && target.closest("input, textarea, select, [contenteditable='true']");
  if (editing) return;
  const modifier = event.ctrlKey || event.metaKey;
  if (modifier && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) redoGraphEdit();
    else undoGraphEdit();
    return;
  }
  if (modifier && event.key.toLowerCase() === "y") {
    event.preventDefault();
    redoGraphEdit();
    return;
  }
  if (event.key === "Delete" || event.key === "Backspace") {
    if (selectedEdgeKey) {
      event.preventDefault();
      deleteSelectedEdge();
    } else if (selectedNodeId && !ui.deleteNode.disabled) {
      event.preventDefault();
      deleteNode();
    }
  }
});
setPointerMirrorUi(pointerMirrorX);
refreshHistoryButtons();
window.addEventListener("pagehide", () => {
  if (pointerModeEnabled) {
    fetch("/api/pointer/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: false }),
      keepalive: true,
    }).catch(() => {});
  }
  if (pointerCalibrationSession) cancelPointerCalibration(false);
  setPointerDiagnosticsOpen(false);
  releaseHandPointer();
});

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
    moveNode(payload.slice(5), event.clientX, event.clientY, mouseDragOffset);
    mouseDragOffset = null;
    if (mouseHistoryBefore) pushGraphHistory(mouseHistoryBefore);
    mouseHistoryBefore = null;
  } else if (payload.startsWith("node-type:")) {
    const node = defaultNode(payload.slice(10));
    addNode(node, { edgeKey: findNearestEdgeKey(event.clientX, event.clientY), position });
  } else if (payload.startsWith("action:")) {
    const node = defaultNode("action", payload.slice(7));
    addNode(node, { edgeKey: findNearestEdgeKey(event.clientX, event.clientY), position });
  }
});
window.addEventListener("resize", renderPointerCalibrationOverlay);
window.addEventListener("scroll", renderPointerCalibrationOverlay, true);
ui.canvasViewport.addEventListener("scroll", renderPointerCalibrationOverlay, { passive: true });

setInterval(() => {
  refreshRuns().catch(() => {});
  refreshDisplayStatus().catch(() => {});
  refreshPointerMode().catch(() => {});
}, 3000);
connectWorkflowEvents();
refreshPointerMode().catch(() => {});
initialize();
