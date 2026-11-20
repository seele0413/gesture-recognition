const ui = {
  workflowSelect: document.getElementById("workflowSelect"),
  workflowName: document.getElementById("workflowName"),
  workflowDescription: document.getElementById("workflowDescription"),
  workflowVersion: document.getElementById("workflowVersion"),
  newWorkflow: document.getElementById("newWorkflow"),
  generateWorkflow: document.getElementById("generateWorkflow"),
  workflowGeneratorDialog: document.getElementById("workflowGeneratorDialog"),
  workflowGeneratorForm: document.getElementById("workflowGeneratorForm"),
  workflowGeneratorFile: document.getElementById("workflowGeneratorFile"),
  workflowGeneratorApiKey: document.getElementById("workflowGeneratorApiKey"),
  workflowGeneratorBaseUrl: document.getElementById("workflowGeneratorBaseUrl"),
  workflowGeneratorModel: document.getElementById("workflowGeneratorModel"),
  workflowGeneratorProtocol: document.getElementById("workflowGeneratorProtocol"),
  workflowGeneratorKeyState: document.getElementById("workflowGeneratorKeyState"),
  saveWorkflowGeneratorConfig: document.getElementById("saveWorkflowGeneratorConfig"),
  testWorkflowGeneratorConnection: document.getElementById("testWorkflowGeneratorConnection"),
  workflowGeneratorInstructions: document.getElementById("workflowGeneratorInstructions"),
  workflowGeneratorTrigger: document.getElementById("workflowGeneratorTrigger"),
  workflowGeneratorStatus: document.getElementById("workflowGeneratorStatus"),
  workflowGeneratorSubmit: document.getElementById("workflowGeneratorSubmit"),
  workflowGeneratorResult: document.getElementById("workflowGeneratorResult"),
  workflowGeneratorSummary: document.getElementById("workflowGeneratorSummary"),
  workflowGeneratorReport: document.getElementById("workflowGeneratorReport"),
  applyGeneratedWorkflow: document.getElementById("applyGeneratedWorkflow"),
  regenerateWorkflow: document.getElementById("regenerateWorkflow"),
  closeWorkflowGenerator: document.getElementById("closeWorkflowGenerator"),
  cancelWorkflowGenerator: document.getElementById("cancelWorkflowGenerator"),
  copyWorkflow: document.getElementById("copyWorkflow"),
  saveWorkflow: document.getElementById("saveWorkflow"),
  deleteWorkflow: document.getElementById("deleteWorkflow"),
  validateWorkflow: document.getElementById("validateWorkflow"),
  dryRunWorkflow: document.getElementById("dryRunWorkflow"),
  toggleWorkflow: document.getElementById("toggleWorkflow"),
  actionLibrary: document.getElementById("actionLibrary"),
  gestureWorkflowMap: document.getElementById("gestureWorkflowMap"),
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
  workflowInspector: document.getElementById("workflowInspector"),
  inspectorClose: document.getElementById("inspectorClose"),
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
let workflowIsDraft = false;
let generatedWorkflowPreview = null;
let actionDefinitions = [];
let selectedNodeId = null;
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
  return PointerGeometry.clientToWorld(
    { x: clientX, y: clientY },
    rect,
    ui.canvasViewport.scrollLeft,
    ui.canvasViewport.scrollTop,
    zoom,
  );
}

function releaseHandPointer() {
  if (pointerAnimationFrame !== null) {
    window.cancelAnimationFrame(pointerAnimationFrame);
    pointerAnimationFrame = null;
  }
  pointerEventBuffer?.clear();
  pointerMetrics.lastRafScheduledAt = null;
  if (pointerDragNodeId) pointerMetrics.dragCancels += 1;
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
    selectedNodeId = nodeId;
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
  if (!pointerMoved && !pointerDragNodeId && pointerDownTarget instanceof HTMLElement) {
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

function currentNode() {
  return workflow?.nodes.find((node) => node.id === selectedNodeId) || null;
}

function setMessage(message, state = "ok") {
  ui.validationMessage.textContent = message;
  ui.validationMessage.dataset.state = state;
}

function setEditingEnabled(enabled) {
  [ui.saveWorkflow, ui.validateWorkflow, ui.dryRunWorkflow].forEach((button) => {
    button.disabled = !enabled;
  });
  [ui.copyWorkflow, ui.deleteWorkflow, ui.toggleWorkflow].forEach((button) => {
    button.disabled = !enabled || workflowIsDraft;
  });
  ui.workflowName.disabled = !enabled;
  ui.workflowDescription.disabled = !enabled;
  ui.workflowVersion.disabled = !enabled || workflowIsDraft;
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
  renderGestureWorkflowMap();
}

function workflowTriggerLabel(trigger) {
  if (!trigger) return "未设置触发器";
  if (trigger.type === "gesture_trigger") return GESTURE_LABELS[trigger.gesture] || trigger.gesture;
  if (trigger.type === "gesture_sequence_trigger") {
    return (trigger.gestures || []).map((gesture) => GESTURE_LABELS[gesture] || gesture).join(" → ");
  }
  return "主控锁定";
}

function workflowTargetLabel(definition) {
  const nodes = Array.isArray(definition.nodes) ? definition.nodes : [];
  const navigation = nodes.find((node) => node.type === "action" && node.action === "web.navigate_page");
  const pageId = navigation?.params?.page_id;
  if (pageId) return "目标页面 · " + pageId;
  if (nodes.some((node) => node.type === "action" && String(node.action || "").startsWith("web."))) {
    return "当前展示页面";
  }
  return "由动作节点决定";
}

function renderGestureWorkflowMap() {
  if (!ui.gestureWorkflowMap) return;
  ui.gestureWorkflowMap.replaceChildren();
  const entries = workflows.filter((item) => item.trigger?.type !== "controller_locked");
  if (!entries.length) {
    ui.gestureWorkflowMap.append(make("p", "muted", "暂无手势工作流。新建工作流，在上方选择启动手势，再添加网页或视频动作节点。"));
    return;
  }
  for (const item of entries) {
    const row = make("button", "gesture-map-row");
    row.type = "button";
    row.dataset.active = String(item.id === workflow?.id);
    row.title = "打开工作流：" + item.name;
    const trigger = make("span", "gesture-map-trigger", workflowTriggerLabel(item.trigger));
    const name = make("span", "gesture-map-name", item.name);
    const state = make(
      "span",
      "gesture-map-meta",
      (item.enabled ? "已启用" : "未启用") + " · " + workflowTargetLabel(item),
    );
    row.append(trigger, name, state);
    row.addEventListener("click", () => {
      if (workflowIsDraft && !window.confirm("切换工作流会丢弃当前 AI 草稿，是否继续？")) return;
      loadWorkflow(item.id).catch((error) => setMessage(error.message, "error"));
    });
    ui.gestureWorkflowMap.append(row);
  }
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
  workflowIsDraft = false;
  selectedNodeId = null;
  closeInspector();
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
    const isCurrent = Number(item.version) === Number(workflow.version);
    const option = make("option", "", "v" + item.version + (isCurrent ? "（当前）" : "（历史）"));
    option.value = String(item.version);
    option.title = isCurrent ? "当前工作流版本" : "历史版本；选择后可回看旧配置，保存修改会生成新版本";
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
  nodeCardsById.clear();
  nodeModelsById.clear();
  if (!workflow) {
    ui.canvasNodes.replaceChildren();
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
    card.title = "左键选择节点 · 右键打开参数设置";
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
    card.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      openInspector(node.id);
    });
    card.addEventListener("dragstart", (event) => {
      const worldPoint = clientToWorld(event.clientX, event.clientY);
      mouseDragOffset = {
        x: worldPoint.x - node.position.x,
        y: worldPoint.y - node.position.y,
      };
      event.dataTransfer.setData("text/plain", "node:" + node.id);
      event.dataTransfer.effectAllowed = "move";
    });
    card.addEventListener("dragend", () => { mouseDragOffset = null; });
    nodeCardsById.set(node.id, card);
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
  record.path.setAttribute("d", `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
  if (record.labelElement) {
    record.labelElement.setAttribute("x", String((x1 + x2) / 2));
    record.labelElement.setAttribute("y", String((y1 + y2) / 2 - 7));
  }
}

function addEdgeRecord(svg, key, sourceId, targetId, styleKey, label) {
  const namespace = "http://www.w3.org/2000/svg";
  const path = document.createElementNS(namespace, "path");
  path.dataset.edge = key;
  path.dataset.source = sourceId;
  path.dataset.target = targetId;
  if (styleKey === "error") path.classList.add("edge-error");
  svg.append(path);
  let labelElement = null;
  if (label) {
    labelElement = document.createElementNS(namespace, "text");
    labelElement.dataset.edgeLabel = key;
    labelElement.textContent = label;
    svg.append(labelElement);
  }
  const record = { key, sourceId, targetId, path, labelElement };
  edgeRecords.set(key, record);
  indexEdgeForNode(sourceId, key);
  indexEdgeForNode(targetId, key);
  updateEdgeRecord(record);
}

function drawEdges() {
  const svg = ui.edgeLayer;
  svg.querySelectorAll("path[data-edge], text[data-edge-label]").forEach((element) => element.remove());
  edgeRecords.clear();
  edgeKeysByNode.clear();
  if (!workflow) return;
  const root = workflow.nodes.find((node) => !workflow.edges.some((edge) => edge.target === node.id));
  if (root) addEdgeRecord(svg, "trigger:" + root.id, "trigger", root.id, "trigger", "");
  workflow.edges.forEach((edge, index) => {
    const key = "edge:" + index + ":" + edge.source + ":" + edge.target + ":" + (edge.when || "normal");
    addEdgeRecord(svg, key, edge.source, edge.target, edge.when === "error" ? "error" : edge.source, edge.when || "");
  });
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

function openInspector(nodeId) {
  if (!findNode(nodeId)) return;
  selectedNodeId = nodeId;
  updateNodeSelectionState();
  renderInspector();
  ui.workflowInspector.hidden = false;
  ui.workflowInspector.setAttribute("aria-hidden", "false");
}

function closeInspector() {
  if (!ui.workflowInspector) return;
  ui.workflowInspector.hidden = true;
  ui.workflowInspector.setAttribute("aria-hidden", "true");
}

function renderInspector() {
  ui.inspectorContent.replaceChildren();
  const node = currentNode();
  ui.duplicateNode.disabled = !node || node.type === "condition" || node.type === "end";
  ui.deleteNode.disabled = !node;
  if (!node) {
    ui.inspectorContent.append(make("p", "muted", "右键点击画布节点，打开参数设置"));
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
  node.position = PointerGeometry.nodePositionFromPointer(
    worldPoint,
    offset,
    { width: ui.canvasWorld.clientWidth, height: ui.canvasWorld.clientHeight },
    { width: card?.offsetWidth || 236, height: card?.offsetHeight || 106 },
  );
  if (card) {
    card.style.left = node.position.x + "px";
    card.style.top = node.position.y + "px";
  }
  drawEdgesForNode(nodeId);
  recordPointerDragUpdate(performance.now() - startedAt);
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
  if (!workflow) return;
  updateHeaderData();
  const isNewDraft = workflowIsDraft;
  const endpoint = isNewDraft
    ? "/api/workflows"
    : "/api/workflows/" + encodeURIComponent(workflow.id);
  const response = await api(endpoint, {
    method: isNewDraft ? "POST" : "PUT",
    body: JSON.stringify(workflow),
  });
  workflow = response.workflow;
  workflowIsDraft = false;
  await reloadWorkflowList();
  await loadVersions();
  refreshHeader();
  setMessage(isNewDraft ? "AI 工作流草稿已保存为 v" + workflow.version : "已保存为版本 v" + workflow.version);
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
  workflowIsDraft = false;
  selectedNodeId = null;
  await reloadWorkflowList();
  if (workflows.length) await loadWorkflow(workflows[0].id);
  else {
    closeInspector();
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
  closeInspector();
  setMessage("节点已移除；请连接剩余节点并校验", "error");
}

function appendGeneratorReportSection(title, items, className) {
  const section = make("section", className);
  section.append(make("h4", "", title));
  const list = make("ul");
  for (const item of items) list.append(make("li", "", String(item)));
  section.append(list);
  ui.workflowGeneratorReport.append(section);
}

function renderWorkflowGeneratorResult(result) {
  generatedWorkflowPreview = result;
  const generated = result.workflow;
  const nodeCount = Array.isArray(generated?.nodes) ? generated.nodes.length : 0;
  const edgeCount = Array.isArray(generated?.edges) ? generated.edges.length : 0;
  ui.workflowGeneratorSummary.textContent =
    (result.summary || generated?.description || "已根据文档生成工作流草稿。") +
    " · " + nodeCount + " 个节点 · " + edgeCount + " 条连线";
  ui.workflowGeneratorReport.replaceChildren();

  const errors = Array.isArray(result.validation_errors) ? result.validation_errors : [];
  const warnings = Array.isArray(result.warnings) ? result.warnings : [];
  const questions = Array.isArray(result.questions) ? result.questions : [];
  if (errors.length) appendGeneratorReportSection("需要修正的校验错误", errors, "report-error");
  if (warnings.length) appendGeneratorReportSection("生成假设与提醒", warnings, "report-warning");
  if (questions.length) appendGeneratorReportSection("需要你确认的问题", questions, "report-question");
  if (!errors.length && !warnings.length && !questions.length) {
    appendGeneratorReportSection("检查结果", ["结构校验通过，没有发现需要额外确认的事项。"], "report-ok");
  }

  ui.workflowGeneratorResult.hidden = false;
  ui.applyGeneratedWorkflow.disabled = !generated;
  ui.applyGeneratedWorkflow.textContent = errors.length ? "应用到画布（需修正）" : "应用到画布";
  ui.workflowGeneratorStatus.textContent = errors.length
    ? "已生成草稿，但存在校验错误。可以先应用到画布，修正后再保存。"
    : "生成完成。请检查节点参数、页面跳转和流程分支。";
  ui.workflowGeneratorStatus.dataset.state = errors.length ? "error" : "success";
}

function workflowGeneratorConfigPayload() {
  return {
    api_key: ui.workflowGeneratorApiKey.value.trim() || null,
    base_url: ui.workflowGeneratorBaseUrl.value.trim(),
    model: ui.workflowGeneratorModel.value.trim(),
    protocol: ui.workflowGeneratorProtocol.value,
  };
}

async function refreshWorkflowGeneratorStatus() {
  const status = await api("/api/workflow-generator/status");
  ui.workflowGeneratorBaseUrl.value = status.base_url || "https://api.openai.com/v1";
  ui.workflowGeneratorModel.value = status.model || "gpt-4o-mini";
  ui.workflowGeneratorProtocol.value = status.protocol || "auto";
  if (status.configured) {
    ui.workflowGeneratorKeyState.textContent = "密钥已配置";
    ui.workflowGeneratorApiKey.placeholder = "留空保留当前密钥；输入新 Key 可替换";
    ui.workflowGeneratorStatus.textContent =
      "当前模型：" + status.model + " · " + status.protocol_label + " · " + status.base_url;
    ui.workflowGeneratorStatus.dataset.state = "success";
    ui.workflowGeneratorSubmit.disabled = false;
  } else {
    ui.workflowGeneratorKeyState.textContent = "尚未配置密钥";
    ui.workflowGeneratorApiKey.placeholder = "粘贴中转站或官方服务商 API Key";
    ui.workflowGeneratorStatus.textContent =
      "请填写 API Key、Base URL 和模型名称，保存配置并测试连接后再生成。";
    ui.workflowGeneratorStatus.dataset.state = "error";
    ui.workflowGeneratorSubmit.disabled = true;
  }
}

async function saveWorkflowGeneratorConfig() {
  ui.saveWorkflowGeneratorConfig.disabled = true;
  ui.saveWorkflowGeneratorConfig.textContent = "保存中…";
  try {
    const status = await api("/api/workflow-generator/config", {
      method: "PUT",
      body: JSON.stringify(workflowGeneratorConfigPayload()),
    });
    ui.workflowGeneratorApiKey.value = "";
    ui.workflowGeneratorKeyState.textContent = status.configured ? "密钥已配置" : "尚未配置密钥";
    ui.workflowGeneratorApiKey.placeholder = status.configured
      ? "留空保留当前密钥；输入新 Key 可替换"
      : "粘贴中转站或官方服务商 API Key";
    ui.workflowGeneratorStatus.textContent =
      "模型配置已保存：" + status.model + " · " + status.protocol_label + "。建议先测试连接。";
    ui.workflowGeneratorStatus.dataset.state = status.configured ? "success" : "error";
    ui.workflowGeneratorSubmit.disabled = !status.configured;
  } catch (error) {
    ui.workflowGeneratorStatus.textContent = error.message || "模型配置保存失败";
    ui.workflowGeneratorStatus.dataset.state = "error";
  } finally {
    ui.saveWorkflowGeneratorConfig.disabled = false;
    ui.saveWorkflowGeneratorConfig.textContent = "保存配置";
  }
}

async function testWorkflowGeneratorConnection() {
  ui.testWorkflowGeneratorConnection.disabled = true;
  ui.testWorkflowGeneratorConnection.textContent = "测试中…";
  ui.workflowGeneratorStatus.textContent = "正在连接模型服务并发送一条最小测试请求…";
  ui.workflowGeneratorStatus.dataset.state = "";
  try {
    const result = await api("/api/workflow-generator/test", {
      method: "POST",
      body: JSON.stringify(workflowGeneratorConfigPayload()),
    });
    const saved = await api("/api/workflow-generator/status");
    const matchesSavedConfig =
      !ui.workflowGeneratorApiKey.value.trim() &&
      saved.configured &&
      saved.base_url === ui.workflowGeneratorBaseUrl.value.trim() &&
      saved.model === ui.workflowGeneratorModel.value.trim() &&
      saved.protocol === ui.workflowGeneratorProtocol.value;
    ui.workflowGeneratorKeyState.textContent = "连接测试成功";
    ui.workflowGeneratorStatus.textContent = result.message + " 模型：" + result.model +
      "；实际接口：" + result.protocol_label +
      (matchesSavedConfig ? "。当前已保存配置可直接生成。" : "。这是未保存配置的测试结果；点击“保存配置”后才能用于生成。");
    ui.workflowGeneratorStatus.dataset.state = "success";
    ui.workflowGeneratorSubmit.disabled = !matchesSavedConfig;
  } catch (error) {
    ui.workflowGeneratorStatus.textContent = error.message || "连接测试失败";
    ui.workflowGeneratorStatus.dataset.state = "error";
  } finally {
    ui.testWorkflowGeneratorConnection.disabled = false;
    ui.testWorkflowGeneratorConnection.textContent = "测试连接";
  }
}

function openWorkflowGenerator() {
  if (workflow && !window.confirm("AI 生成结果将替换当前画布内容。当前未保存的修改会丢失，是否继续？")) return;
  generatedWorkflowPreview = null;
  ui.workflowGeneratorApiKey.value = "";
  ui.workflowGeneratorResult.hidden = true;
  ui.workflowGeneratorFile.value = "";
  ui.workflowGeneratorStatus.dataset.state = "";
  ui.workflowGeneratorStatus.textContent = "正在检查模型配置…";
  ui.workflowGeneratorSubmit.disabled = true;
  ui.workflowGeneratorDialog.showModal();
  refreshWorkflowGeneratorStatus().catch((error) => {
    ui.workflowGeneratorStatus.textContent = "无法读取模型配置：" + error.message;
    ui.workflowGeneratorStatus.dataset.state = "error";
  });
}

async function submitWorkflowGenerator(event) {
  event.preventDefault();
  const file = ui.workflowGeneratorFile.files?.[0];
  if (!file) {
    ui.workflowGeneratorStatus.textContent = "请先选择一份需求文档。";
    ui.workflowGeneratorStatus.dataset.state = "error";
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    ui.workflowGeneratorStatus.textContent = "文件不能超过 5 MB。";
    ui.workflowGeneratorStatus.dataset.state = "error";
    return;
  }

  ui.workflowGeneratorSubmit.disabled = true;
  ui.workflowGeneratorSubmit.textContent = "正在解析文档并生成…";
  ui.workflowGeneratorResult.hidden = true;
  ui.workflowGeneratorStatus.textContent = "正在读取文档、分析业务步骤并构建节点，请稍候…";
  ui.workflowGeneratorStatus.dataset.state = "";
  try {
    const formData = new FormData(ui.workflowGeneratorForm);
    const response = await fetch("/api/workflows/generate", {
      method: "POST",
      cache: "no-store",
      body: formData,
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(result.detail) ? result.detail.join("；") : result.detail;
      throw new Error(detail || "文档解析失败，请检查文件和模型配置");
    }
    renderWorkflowGeneratorResult(result);
  } catch (error) {
    ui.workflowGeneratorStatus.textContent = error.message || "生成失败，请稍后重试";
    ui.workflowGeneratorStatus.dataset.state = "error";
  } finally {
    ui.workflowGeneratorSubmit.disabled = false;
    ui.workflowGeneratorSubmit.textContent = "解析并生成草稿";
  }
}

function applyGeneratedWorkflow() {
  if (!generatedWorkflowPreview?.workflow) return;
  workflow = structuredClone(generatedWorkflowPreview.workflow);
  workflow.enabled = false;
  workflowIsDraft = true;
  selectedNodeId = null;
  linkSourceId = null;
  nodeStatuses.clear();
  activeRunId = null;
  ui.workflowVersion.replaceChildren(make("option", "", "未保存草稿"));
  ui.workflowVersion.value = "";
  refreshHeader();
  renderTrigger();
  renderCanvas();
  renderInspector();
  const errors = generatedWorkflowPreview.validation_errors || [];
  ui.workflowGeneratorDialog.close();

  setMessage(
    errors.length
      ? "AI 草稿已载入画布，但有 " + errors.length + " 项校验错误。修正后再保存。"
      : "AI 草稿已载入画布。请检查节点参数，执行校验和模拟后再保存。",
    errors.length ? "error" : "ok",
  );
}

function resetWorkflowGeneratorPreview() {
  generatedWorkflowPreview = null;
  ui.workflowGeneratorResult.hidden = true;
  ui.workflowGeneratorReport.replaceChildren();
  ui.workflowGeneratorFile.value = "";
  ui.workflowGeneratorApiKey.value = "";
  ui.workflowGeneratorStatus.dataset.state = "";
  ui.workflowGeneratorStatus.textContent = "请选择文档并补充生成要求。";
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
  refreshWorkflowGeneratorStatus().catch((error) => {
    ui.workflowGeneratorStatus.textContent = "模型配置检查失败：" + error.message;
    ui.workflowGeneratorStatus.dataset.state = "error";
    ui.workflowGeneratorSubmit.disabled = true;
  });
}

ui.newWorkflow.addEventListener("click", () => {
  if (workflowIsDraft && !window.confirm("新建工作流会丢弃当前 AI 草稿，是否继续？")) return;
  createWorkflow().catch((error) => setMessage(error.message, "error"));
});
ui.generateWorkflow.addEventListener("click", openWorkflowGenerator);
ui.saveWorkflowGeneratorConfig.addEventListener("click", saveWorkflowGeneratorConfig);
ui.testWorkflowGeneratorConnection.addEventListener("click", testWorkflowGeneratorConnection);
ui.workflowGeneratorApiKey.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    saveWorkflowGeneratorConfig();
  }
});
ui.workflowGeneratorForm.addEventListener("submit", submitWorkflowGenerator);
ui.applyGeneratedWorkflow.addEventListener("click", applyGeneratedWorkflow);
ui.regenerateWorkflow.addEventListener("click", () => {
  generatedWorkflowPreview = null;
  ui.workflowGeneratorResult.hidden = true;
  ui.workflowGeneratorSubmit.disabled = false;
  ui.workflowGeneratorStatus.textContent = "可以修改补充要求后重新生成。";
  ui.workflowGeneratorStatus.dataset.state = "";
});
ui.closeWorkflowGenerator.addEventListener("click", () => ui.workflowGeneratorDialog.close());
ui.cancelWorkflowGenerator.addEventListener("click", () => ui.workflowGeneratorDialog.close());
ui.workflowGeneratorDialog.addEventListener("close", resetWorkflowGeneratorPreview);
ui.copyWorkflow.addEventListener("click", () => duplicateWorkflow().catch((error) => setMessage(error.message, "error")));
ui.deleteWorkflow.addEventListener("click", () => deleteWorkflow().catch((error) => setMessage(error.message, "error")));
ui.saveWorkflow.addEventListener("click", () => saveWorkflow().catch((error) => setMessage(error.message, "error")));
ui.validateWorkflow.addEventListener("click", () => validateCurrent().catch((error) => setMessage(error.message, "error")));
ui.dryRunWorkflow.addEventListener("click", () => dryRun().catch((error) => setMessage(error.message, "error")));
ui.toggleWorkflow.addEventListener("click", () => toggleWorkflow().catch((error) => setMessage(error.message, "error")));
ui.workflowSelect.addEventListener("change", () => {
  if (workflowIsDraft && !window.confirm("切换工作流会丢弃当前 AI 草稿，是否继续？")) {
    ui.workflowSelect.value = "";
    return;
  }
  loadWorkflow(ui.workflowSelect.value).catch((error) => setMessage(error.message, "error"));
});
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
  closeInspector();
  refreshHeader();
  renderTrigger();
  renderCanvas();
  renderInspector();
  setMessage("已载入历史版本 v" + item.version + "；修改并保存后会创建新版本");
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
ui.inspectorClose.addEventListener("click", closeInspector);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !ui.workflowInspector.hidden) closeInspector();
});
ui.pointerMode.addEventListener("click", () => togglePointerMode());
ui.pointerMirror.addEventListener("click", () => setPointerMirrorUi(!pointerMirrorX));
ui.pointerCalibrate.addEventListener("click", startPointerCalibration);
ui.pointerDiagnostics.addEventListener("click", () => setPointerDiagnosticsOpen(ui.pointerDiagnosticsPanel.hidden));
ui.pointerDiagnosticsClose.addEventListener("click", () => setPointerDiagnosticsOpen(false));
ui.pointerDiagnosticsReset.addEventListener("click", resetPointerDiagnostics);
ui.pointerDiagnosticsExport.addEventListener("click", () => exportPointerDiagnostics().catch((error) => setMessage(error.message, "error")));
setPointerMirrorUi(pointerMirrorX);
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
  } else if (payload.startsWith("node-type:")) {
    const node = defaultNode(payload.slice(10)); node.position = position; addNode(node);
  } else if (payload.startsWith("action:")) {
    const node = defaultNode("action", payload.slice(7)); node.position = position; addNode(node);
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
