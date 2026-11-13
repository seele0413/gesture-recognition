const GESTURES = [
  ["Open_Palm", "张开手掌"],
  ["Closed_Fist", "握拳"],
  ["Thumb_Up", "竖拇指"],
  ["Thumb_Down", "拇指向下"],
  ["Pointing_Up", "食指向上"],
  ["Victory", "比耶手势（主控锁定）"],
  ["ILoveYou", "我爱你手势"],
];

const ACTIONS = [
  ["none", "不执行"],
  ["play_pause", "播放 / 暂停"],
  ["volume_up", "音量增加"],
  ["volume_down", "音量降低"],
  ["mute_toggle", "静音切换"],
];

const HAND_CONNECTIONS = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [0, 9], [9, 10], [10, 11], [11, 12],
  [0, 13], [13, 14], [14, 15], [15, 16],
  [0, 17], [17, 18], [18, 19], [19, 20],
  [5, 9], [9, 13], [13, 17],
];

const elements = Object.fromEntries(
  [
    "connectionStatus", "connectionLabel", "streamError", "streamForm", "rtspUrl", "toggleRtspVisibility",
    "startStream", "stopStream", "videoFrame", "videoFeed", "personOverlay", "videoPlaceholder",
    "resolutionLabel", "candidateCount", "targetLabel", "visionDiagnostics", "handDiagnostics", "trackCount", "controllerCard", "controllerStatus",
    "controllerTrackId", "controllerDetail", "unlockController", "trackList", "mappingGrid", "saveMappings",
    "mappingStatus", "eventList", "clearEvents", "pipelineDiagnostics", "gestureConfidenceRange", "confidenceValue", "confidenceStatus",
  ].map((id) => [id, document.getElementById(id)]),
);

let appState = {
  state: "stopped",
  tracks: [],
  frame_width: 0,
  frame_height: 0,
  controller: { state: "unlocked", track_id: null },
};
let mappings = {};
let confidenceSaveTimer;
let confidenceSaveQueue = Promise.resolve();

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "请求失败");
  return payload;
}

function setStatus(state, message) {
  const labels = { stopped: "未连接", connecting: "连接中", running: "运行中", reconnecting: "自动重连中", error: "连接异常" };
  elements.connectionStatus.dataset.state = state;
  elements.connectionLabel.textContent = message || labels[state] || "未连接";
  elements.startStream.disabled = state === "connecting" || state === "running" || state === "reconnecting";
  elements.stopStream.disabled = state === "stopped";
}

function setVideoSize(width, height) {
  if (width && height) elements.videoFrame.style.aspectRatio = width + " / " + height;
}

function drawTracks() {
  const canvas = elements.personOverlay;
  const context = canvas.getContext("2d");
  const width = elements.videoFrame.clientWidth;
  const height = elements.videoFrame.clientHeight;
  if (!width || !height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);
  if (!appState.frame_width || !appState.frame_height) return;
  const frameGap = Math.abs((appState.preview_frame_sequence || 0) - (appState.vision_frame_sequence || 0));
  const maxOverlayGap = Math.max(2, Math.round((appState.preview_fps || 20) * 0.25));
  if (frameGap > maxOverlayGap) return;
  const controller = appState.controller || {};
  for (const track of appState.tracks || []) {
    const [x, y, boxWidth, boxHeight] = track.box_norm || [
      track.box[0] / appState.frame_width,
      track.box[1] / appState.frame_height,
      track.box[2] / appState.frame_width,
      track.box[3] / appState.frame_height,
    ];
    const left = x * width;
    const top = y * height;
    const drawWidth = boxWidth * width;
    const drawHeight = boxHeight * height;
    const isController = track.track_id && track.track_id === controller.track_id;
    context.strokeStyle = isController ? "#d0b56d" : track.ambiguous ? "#bd7165" : "#70a27a";
    context.lineWidth = isController ? 3 : 2;
    context.strokeRect(left, top, drawWidth, drawHeight);
    const label = track.track_id || "关联不明确";
    context.font = "12px Segoe UI, Microsoft YaHei UI, sans-serif";
    const labelWidth = context.measureText(label).width + 12;
    context.fillStyle = isController ? "#745e2f" : "#405c45";
    context.fillRect(left, Math.max(0, top - 22), labelWidth, 20);
    context.fillStyle = "#fff";
    context.fillText(label, left + 6, Math.max(0, top - 8));
  }

  for (const hand of appState.vision?.hands || []) {
    const points = hand.landmarks || [];
    if (points.length !== 21) continue;
    const color = hand.is_lock_gesture ? "#d7bc74" : "#77c7cb";
    context.strokeStyle = color;
    context.fillStyle = color;
    context.lineWidth = 1.5;
    context.beginPath();
    for (const [start, end] of HAND_CONNECTIONS) {
      context.moveTo(points[start].x * width, points[start].y * height);
      context.lineTo(points[end].x * width, points[end].y * height);
    }
    context.stroke();
    for (const point of points) {
      context.beginPath();
      context.arc(point.x * width, point.y * height, 2, 0, Math.PI * 2);
      context.fill();
    }
    const handLabel = (hand.handedness || "手") + " · " + (hand.track_id || "未关联");
    context.font = "11px Segoe UI, Microsoft YaHei UI, sans-serif";
    const labelWidth = context.measureText(handLabel).width + 10;
    const labelX = points[0].x * width;
    const labelY = Math.max(0, points[0].y * height - 19);
    context.fillStyle = hand.is_lock_gesture ? "#745e2f" : "#315e60";
    context.fillRect(labelX, labelY, labelWidth, 17);
    context.fillStyle = "#fff";
    context.fillText(handLabel, labelX + 5, labelY + 12);
  }
}

function renderTracks() {
  const tracks = appState.tracks || [];
  const controller = appState.controller || { state: "unlocked", track_id: null };
  elements.trackCount.textContent = String(tracks.length);
  elements.candidateCount.textContent = "画面中 " + tracks.length + " 人";
  elements.resolutionLabel.textContent = appState.frame_width
    ? appState.frame_width + " × " + appState.frame_height
    : "-- × --";

  const hasFrame = appState.state === "running" && Boolean(appState.frame_ready);
  elements.videoFeed.hidden = !hasFrame;
  elements.videoPlaceholder.hidden = hasFrame;
  if (!hasFrame) {
    elements.videoPlaceholder.textContent = appState.state === "reconnecting"
      ? "视频流中断，正在自动重连"
      : appState.state === "running"
        ? appState.frame_age_ms == null ? "已连接，等待首帧" : "画面停滞，等待新帧"
        : "等待视频流";
  }

  elements.controllerCard.dataset.state = controller.state;
  const labels = { unlocked: "未锁定", locked: "已锁定", lost: "跟踪中断 · 控制暂停" };
  elements.controllerStatus.textContent = labels[controller.state] || "未锁定";
  elements.controllerTrackId.textContent = controller.track_id || "--";
  elements.targetLabel.textContent = controller.state === "locked"
    ? "主控：" + controller.track_id
    : controller.state === "lost" ? "主控暂时丢失" : "主控未锁定";
  elements.unlockController.disabled = controller.state === "unlocked";
  elements.controllerDetail.textContent = controller.state === "locked"
    ? "主控轨迹有效"
    : controller.state === "lost"
      ? "信号丢失 · 控制暂停"
      : appState.state === "running"
        ? tracks.length
          ? "保持比耶手势 · " + (controller.lock_progress || 0) + "/" + (controller.lock_required_frames || 3) + "（最近 " + (controller.lock_window_frames || 5) + " 帧）"
          : "未检测到肩部轨迹；请让双肩进入画面并保持清晰"
        : appState.state === "reconnecting" ? "视频流恢复后需要重新做比耶手势锁定" : "视频流未启动";

  const vision = appState.vision || {};
  const ambiguousTrackCount = tracks.filter((track) => track.ambiguous).length;
  elements.visionDiagnostics.textContent = "人体轨迹 " + tracks.length
    + " · 明确 " + (tracks.length - ambiguousTrackCount) + " · 歧义 " + ambiguousTrackCount
    + " · 手部 " + (vision.hand_count || 0)
    + " · 比耶 " + (vision.lock_gesture_count || 0)
    + " · 已关联比耶 " + (vision.associated_lock_gesture_count || 0)
    + " · 手部输入 " + (vision.hand_inference_width || 0) + "px"
    + " · 低置信 " + (vision.low_confidence_hand_count || 0)
    + " · 门槛 " + Math.round((vision.confidence_threshold || 0.6) * 100) + "%";
  const visionMs = appState.last_vision_ms;
  const jpegMs = appState.last_jpeg_encode_ms;
  const queueDelayMs = appState.last_queue_delay_ms;
  const timings = vision.timings || {};
  const droppedFrames = appState.dropped_frames || 0;
  elements.pipelineDiagnostics.textContent = visionMs == null
    ? "预览 -- FPS · AI -- FPS · 预处理 -- ms · Pose -- ms · 手势 -- ms · 轨迹 -- ms · 推理 -- ms · JPEG -- ms · 排队 -- ms · 丢帧 " + droppedFrames
    : "预览 " + (appState.preview_fps || 0) + " FPS · AI " + (appState.ai_processing_fps || 0) + " FPS"
      + " · 预处理 " + Math.round(timings.preprocessing_ms || 0) + " ms"
      + " · Pose " + Math.round(timings.pose_inference_ms || 0) + " ms · 手势 " + Math.round(timings.gesture_inference_ms || 0) + " ms"
      + " · 轨迹 " + Math.round(timings.tracking_ms || 0) + " ms · 推理 " + Math.round(visionMs) + " ms · JPEG " + Math.round(jpegMs || 0)
      + " ms · 排队 " + Math.round(queueDelayMs || 0) + " ms · 丢帧 " + droppedFrames;
  const hands = vision.hands || [];
  if (!hands.length) {
    elements.handDiagnostics.textContent = appState.state === "running"
      ? tracks.length
        ? "人体已检测；暂未检测到手部，请举手入镜并避免遮挡"
        : "尚未建立人体轨迹，请确保双肩清晰进入画面"
      : appState.state === "reconnecting"
        ? "摄像头正在重连；控制已暂停，恢复后需重新做比耶手势"
        : "等待识别手部";
  } else {
    elements.handDiagnostics.textContent = hands.slice(0, 3).map((hand) => {
      const gestureName = hand.gesture || "未识别内置手势";
      const confidence = Math.round((hand.confidence || 0) * 100);
      const lockState = hand.is_lock_gesture
        ? "比耶已确认"
        : "比耶未确认：" + hand.lock_gesture_reason;
      return (hand.handedness || "手") + " · " + gestureName + " " + confidence + "% · 锁定 "
        + (appState.controller?.lock_progress || 0) + "/3（5帧窗口） · "
        + lockState + " · " + (hand.lock_track_id || hand.track_id || hand.lock_association_reason || hand.association_reason)
        + " · " + hand.action_reason;
    }).join("  /  ");
  }
  elements.trackList.replaceChildren();
  if (!tracks.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "暂无人体轨迹";
    elements.trackList.append(empty);
  } else {
    for (const track of tracks) {
      const row = document.createElement("div");
      row.className = "track-row";
      const name = document.createElement("span");
      name.className = "track-name";
      name.textContent = track.track_id || "关联不明确";
      const confidence = document.createElement("span");
      confidence.className = "track-confidence";
      confidence.textContent = track.ambiguous
        ? "暂停控制"
        : Math.round((track.association_confidence || 0) * 100) + "%";
      row.append(name, confidence);
      elements.trackList.append(row);
    }
  }
  drawTracks();
}

function syncVideoFeed() {
  if (appState.state === "running") {
    if (!elements.videoFeed.getAttribute("src")) {
      elements.videoFeed.src = "/video.mjpg?settings=" + Date.now();
    }
    return;
  }
  elements.videoFeed.removeAttribute("src");
}

async function refreshStatus() {
  try {
    appState = await api("/api/status");
    setStatus(appState.state, appState.state === "error" ? "连接异常" : undefined);
    elements.streamError.textContent = appState.error || "";
    if (appState.frame_width) setVideoSize(appState.frame_width, appState.frame_height);
    syncVideoFeed();
    renderTracks();
  } catch (error) {
    setStatus("error", "服务未响应");
    elements.streamError.textContent = error.message;
  }
}

async function connectStream(event) {
  event.preventDefault();
  const rtspUrl = elements.rtspUrl.value.trim();
  if (!/^rtsps?:\/\//i.test(rtspUrl)) {
    elements.streamError.textContent = "请输入以 rtsp:// 或 rtsps:// 开头的地址";
    elements.rtspUrl.focus();
    return;
  }
  elements.streamError.textContent = "";
  elements.startStream.disabled = true;
  try {
    await api("/api/stream/start", { method: "POST", body: JSON.stringify({ rtsp_url: rtspUrl }) });
    elements.rtspUrl.value = "";
    await refreshStatus();
  } catch (error) {
    elements.streamError.textContent = error.message;
    elements.startStream.disabled = false;
  }
}

async function stopStream() {
  elements.stopStream.disabled = true;
  try {
    await api("/api/stream/stop", { method: "POST" });
    appState = { ...appState, state: "stopped", tracks: [], controller: { state: "unlocked", track_id: null } };
    syncVideoFeed();
    renderTracks();
    await refreshStatus();
  } catch (error) {
    elements.streamError.textContent = error.message;
  }
}

async function unlockController() {
  elements.unlockController.disabled = true;
  try {
    await api("/api/controller/unlock", { method: "POST" });
    await refreshStatus();
  } catch (error) {
    elements.streamError.textContent = error.message;
  }
}

function buildMappings() {
  elements.mappingGrid.replaceChildren();
  for (const [gesture, label] of GESTURES) {
    const row = document.createElement("div");
    row.className = "mapping-row";
    const gestureLabel = document.createElement("label");
    gestureLabel.textContent = label;
    gestureLabel.htmlFor = "mapping-" + gesture;
    const select = document.createElement("select");
    select.id = "mapping-" + gesture;
    select.dataset.gesture = gesture;
    const reservedForController = gesture === "Victory";
    const availableActions = reservedForController
      ? ACTIONS.filter(([action]) => action === "none")
      : ACTIONS;
    for (const [action, actionLabel] of availableActions) select.add(new Option(actionLabel, action));
    select.value = reservedForController ? "none" : mappings[gesture] || "none";
    select.disabled = reservedForController;
    if (reservedForController) select.title = "比耶手势专用于主控锁定";
    row.append(gestureLabel, select);
    elements.mappingGrid.append(row);
  }
}

async function loadMappings() {
  try {
    mappings = (await api("/api/mappings")).mappings;
    buildMappings();
  } catch (error) {
    elements.mappingStatus.textContent = error.message;
  }
}

async function saveMappings() {
  const next = Object.fromEntries(
    [...elements.mappingGrid.querySelectorAll("select")].map((select) => [select.dataset.gesture, select.value]),
  );
  elements.saveMappings.disabled = true;
  try {
    mappings = (await api("/api/mappings", { method: "PUT", body: JSON.stringify({ mappings: next }) })).mappings;
    elements.mappingStatus.textContent = "映射已保存";
    window.setTimeout(() => { elements.mappingStatus.textContent = ""; }, 1800);
  } catch (error) {
    elements.mappingStatus.textContent = error.message;
  } finally {
    elements.saveMappings.disabled = false;
  }
}

async function loadRecognitionSettings() {
  try {
    const settings = await api("/api/recognition-settings");
    const threshold = Number(settings.gesture_confidence_threshold);
    elements.gestureConfidenceRange.value = String(threshold);
    elements.confidenceValue.value = Math.round(threshold * 100) + "%";
    elements.confidenceValue.textContent = elements.confidenceValue.value;
  } catch (error) {
    elements.confidenceStatus.textContent = error.message;
  }
}

function saveConfidenceThreshold() {
  const threshold = Number(elements.gestureConfidenceRange.value);
  confidenceSaveQueue = confidenceSaveQueue.catch(() => {}).then(async () => {
    try {
      const settings = await api("/api/recognition-settings", {
        method: "PUT",
        body: JSON.stringify({ gesture_confidence_threshold: threshold }),
      });
      if (Number(elements.gestureConfidenceRange.value) === threshold) {
        const saved = Number(settings.gesture_confidence_threshold);
        elements.confidenceStatus.textContent = "已立即应用并保存";
        elements.confidenceValue.value = Math.round(saved * 100) + "%";
      }
    } catch (error) {
      if (Number(elements.gestureConfidenceRange.value) === threshold) {
        elements.confidenceStatus.textContent = error.message;
      }
    }
  });
}

function scheduleConfidenceSave(immediate = false) {
  const threshold = Number(elements.gestureConfidenceRange.value);
  elements.confidenceValue.value = Math.round(threshold * 100) + "%";
  elements.confidenceValue.textContent = elements.confidenceValue.value;
  elements.confidenceStatus.textContent = "应用中…";
  window.clearTimeout(confidenceSaveTimer);
  if (immediate) {
    saveConfidenceThreshold();
  } else {
    confidenceSaveTimer = window.setTimeout(saveConfidenceThreshold, 180);
  }
}

function actionLabel(action) {
  return ACTIONS.find(([value]) => value === action)?.[1] || "不执行";
}

function handleEvent(event) {
  if (event.type === "controller" || event.type === "stream") {
    refreshStatus();
    return;
  }
  if (event.type !== "gesture") return;
  console.log("[gesture-control]", event);
  const row = document.createElement("li");
  row.className = "event-item";
  const primary = document.createElement("div");
  primary.className = "event-primary";
  primary.textContent = (event.target_name || event.target_id) + " · " + (event.gesture || "未知手势");
  const secondary = document.createElement("div");
  secondary.className = "event-secondary";
  const score = Math.round((event.confidence || 0) * 100);
  secondary.textContent = event.target_id + " · " + event.handedness + " · " + score + "% · " + actionLabel(event.action);
  row.append(primary, secondary);
  elements.eventList.prepend(row);
  while (elements.eventList.children.length > 8) elements.eventList.lastElementChild.remove();
}

function connectEvents() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(protocol + "//" + window.location.host + "/ws/events");
  socket.addEventListener("message", (message) => {
    try {
      handleEvent(JSON.parse(message.data));
    } catch (error) {
      console.error("无法解析手势事件", error);
    }
  });
  socket.addEventListener("close", () => window.setTimeout(connectEvents, 1500));
}

elements.streamForm.addEventListener("submit", connectStream);
elements.stopStream.addEventListener("click", stopStream);
elements.toggleRtspVisibility.addEventListener("click", () => {
  const showing = elements.rtspUrl.type === "text";
  elements.rtspUrl.type = showing ? "password" : "text";
  elements.toggleRtspVisibility.textContent = showing ? "显示" : "隐藏";
  elements.toggleRtspVisibility.setAttribute("aria-pressed", String(!showing));
});
elements.unlockController.addEventListener("click", unlockController);
elements.saveMappings.addEventListener("click", saveMappings);
elements.gestureConfidenceRange.addEventListener("input", () => scheduleConfidenceSave());
elements.gestureConfidenceRange.addEventListener("change", () => scheduleConfidenceSave(true));
elements.clearEvents.addEventListener("click", () => elements.eventList.replaceChildren());
window.addEventListener("resize", drawTracks);

loadMappings();
loadRecognitionSettings();
refreshStatus();
window.setInterval(refreshStatus, 250);
connectEvents();
