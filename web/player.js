const elements = {
  video: document.getElementById("promoVideo"),
  movieFrame: document.getElementById("movieFrame"),
  playButton: document.getElementById("playButton"),
  playLabel: document.getElementById("playLabel"),
  fullscreenButton: document.getElementById("fullscreenButton"),
  cameraFeed: document.getElementById("cameraFeed"),
  cameraPlaceholder: document.getElementById("cameraPlaceholder"),
  cameraPlaceholderLabel: document.getElementById("cameraPlaceholderLabel"),
  cameraStatus: document.getElementById("cameraStatus"),
  cameraStatusLabel: document.getElementById("cameraStatusLabel"),
  gestureFeedback: document.getElementById("gestureFeedback"),
  scenePanel: document.getElementById("scenePanel"),
  sceneHeadline: document.getElementById("sceneHeadline"),
  sceneSubhead: document.getElementById("sceneSubhead"),
  sceneNotice: document.getElementById("sceneNotice"),
};

const ACTION_LABELS = {
  none: "不执行",
  play_pause: "播放 / 暂停",
  volume_up: "音量增加",
  volume_down: "音量降低",
  mute_toggle: "静音切换",
};

let status = {
  state: "stopped",
  frame_ready: false,
  controller: { state: "unlocked", track_id: null },
};
let feedbackTimer = 0;
let feedRetryTimer = 0;
let feedFailed = false;
const displayCommandResults = new Map();
const pendingDisplayCommands = new Map();

const PANEL_COPY = {
  welcome: ["欢迎莅临康晋电气", "智能展厅交互"],
  company: ["康晋电气", "专注电气技术与创新"],
  product: ["产品中心", "以可靠产品服务客户"],
  factory: ["智能制造", "持续提升制造品质"],
  presentation: ["演示模式", "康晋电气企业展示"],
};
const ROUTE_PATHS = { home: "/", settings: "/settings", workflows: "/workflows" };

async function api(path) {
  const response = await fetch(path, { cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "请求失败");
  return payload;
}

function showFeedback(message) {
  elements.gestureFeedback.textContent = message;
  window.clearTimeout(feedbackTimer);
  feedbackTimer = window.setTimeout(() => {
    elements.gestureFeedback.textContent = "";
  }, 1700);
}

async function togglePlayback() {
  if (elements.video.paused) {
    try {
      await elements.video.play();
      showFeedback("正在播放");
    } catch (error) {
      showFeedback("视频无法播放，请检查宣传片文件");
      console.error("宣传片播放失败", error);
    }
  } else {
    elements.video.pause();
    showFeedback("已暂停");
  }
}

function renderCamera() {
  const controller = status.controller || { state: "unlocked", track_id: null };
  const streamReady = status.state === "running";
  const frameFresh = Boolean(status.frame_fresh ?? status.frame_ready);
  // Multipart MJPEG remains open; backend frame freshness is the reliable signal.
  const hasImage = streamReady && frameFresh && !feedFailed;

  elements.cameraFeed.hidden = !hasImage;
  elements.cameraPlaceholder.hidden = hasImage;
  if (!streamReady) {
    const reconnecting = status.state === "reconnecting";
    const connecting = status.state === "connecting";
    elements.cameraPlaceholderLabel.textContent = reconnecting
      ? "视频流中断，正在自动重连 · 第 " + (status.reconnect_attempt || 1) + " 次"
      : connecting ? "正在连接摄像头"
        : status.state === "error" ? "摄像头连接异常" : "摄像头未连接";
    elements.cameraStatusLabel.textContent = reconnecting
      ? "正在重连 · " + (status.error || "恢复后需重新锁定主控")
      : status.state === "error"
        ? (status.error || "摄像头连接异常")
        : connecting ? "正在连接摄像头" : "摄像头未连接";
    elements.cameraStatus.dataset.state = status.state;
    return;
  }

  if (!hasImage) {
    elements.cameraPlaceholderLabel.textContent = feedFailed
      ? "预览传输中断，正在重新连接"
      : status.frame_age_ms == null ? "已连接，正在等待首帧"
        : "画面停滞，正在等待新帧";
    elements.cameraStatusLabel.textContent = feedFailed
      ? "MJPEG 预览连接失败，正在自动重订阅"
      : status.frame_age_ms == null
        ? "摄像头已连接，等待视频帧"
        : "视频帧已停滞 " + (status.frame_age_ms / 1000).toFixed(1) + " 秒";
    elements.cameraStatus.dataset.state = "stale";
    return;
  }

  if (controller.state === "locked") {
    elements.cameraStatusLabel.textContent = "主控已锁定";
    elements.cameraStatus.dataset.state = "locked";
  } else if (controller.state === "suspect") {
    elements.cameraStatusLabel.textContent = "主控短暂丢失 · 等待恢复";
    elements.cameraStatus.dataset.state = "suspect";
  } else if (controller.state === "reacquiring" || controller.state === "lost") {
    elements.cameraStatusLabel.textContent = "正在重新寻找原主控 · 控制暂停";
    elements.cameraStatus.dataset.state = "lost";
  } else {
    elements.cameraStatusLabel.textContent = "等待比耶手势锁定";
    elements.cameraStatus.dataset.state = "running";
  }
}

function syncCameraFeed() {
  if (status.state === "running") {
    if (!elements.cameraFeed.getAttribute("src")) {
      feedFailed = false;
      elements.cameraFeed.src = "/video.mjpg?display=" + Date.now();
    }
  } else {
    window.clearTimeout(feedRetryTimer);
    feedFailed = false;
    elements.cameraFeed.removeAttribute("src");
  }
  renderCamera();
}

elements.cameraFeed.addEventListener("error", () => {
  if (status.state !== "running") return;
  feedFailed = true;
  renderCamera();
  window.clearTimeout(feedRetryTimer);
  feedRetryTimer = window.setTimeout(() => {
    if (status.state !== "running") return;
    feedFailed = false;
    elements.cameraFeed.removeAttribute("src");
    elements.cameraFeed.src = "/video.mjpg?display=" + Date.now();
    renderCamera();
  }, 1200);
});

elements.cameraFeed.addEventListener("load", () => {
  feedFailed = false;
  renderCamera();
});

async function refreshStatus() {
  try {
    status = await api("/api/status");
    syncCameraFeed();
  } catch (error) {
    status = { state: "error", error: "服务未响应", controller: { state: "unlocked", track_id: null } };
    renderCamera();
  }
}

function applyAction(action) {
  const video = elements.video;
  switch (action) {
    case "play_pause":
      togglePlayback();
      break;
    case "volume_up":
      video.volume = Math.min(1, Math.round((video.volume + 0.1) * 10) / 10);
      showFeedback("音量 " + Math.round(video.volume * 100) + (video.muted ? "% · 已静音" : "%"));
      break;
    case "volume_down":
      video.volume = Math.max(0, Math.round((video.volume - 0.1) * 10) / 10);
      showFeedback("音量 " + Math.round(video.volume * 100) + (video.muted ? "% · 已静音" : "%"));
      break;
    case "mute_toggle":
      video.muted = !video.muted;
      showFeedback(video.muted ? "已静音" : "已取消静音");
      break;
    default:
      return;
  }
}

function handleEvent(event) {
  if (event.type === "controller" || event.type === "stream") {
    refreshStatus();
    return;
  }
  if (event.type !== "gesture") return;
  console.log("[gesture-control]", event);
  if (event.action_triggered && !event.workflow_handled) applyAction(event.action);
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

function setScene(scene) {
  const scenes = ["welcome", "company_intro", "product_intro", "factory_intro", "presentation_mode"];
  if (!scenes.includes(scene)) throw new Error("未登记的展厅场景");
  document.body.dataset.scene = scene;
  const panels = {
    welcome: "welcome", company_intro: "company", product_intro: "product",
    factory_intro: "factory", presentation_mode: "presentation",
  };
  setPanel(panels[scene], true);
}

function setPanel(panel, visible) {
  if (!Object.hasOwn(PANEL_COPY, panel)) throw new Error("未登记的展示面板");
  if (visible) {
    const [headline, subhead] = PANEL_COPY[panel];
    elements.scenePanel.dataset.panel = panel;
    elements.sceneHeadline.textContent = headline;
    elements.sceneSubhead.textContent = subhead;
    elements.scenePanel.hidden = false;
  } else if (elements.scenePanel.dataset.panel === panel) {
    elements.scenePanel.hidden = true;
  }
}

function setSceneText(field, text) {
  const fields = {
    headline: elements.sceneHeadline,
    subhead: elements.sceneSubhead,
    notice: elements.sceneNotice,
  };
  if (!Object.hasOwn(fields, field) || typeof text !== "string" || text.length > 160) {
    throw new Error("展示文本字段或长度无效");
  }
  fields[field].textContent = text;
}

function seekVideo(positionMs) {
  if (!Number.isInteger(positionMs) || positionMs < 0) throw new Error("视频位置无效");
  if (!Number.isFinite(elements.video.duration)) throw new Error("视频尚未就绪");
  const seconds = positionMs / 1000;
  if (seconds > elements.video.duration) throw new Error("跳转位置超过视频时长");
  elements.video.currentTime = seconds;
  return { current_time_ms: Math.round(elements.video.currentTime * 1000) };
}

async function executeDisplayAction(action, params, timeoutMs = 10000) {
  const video = elements.video;
  switch (action) {
    case "web.navigate_route": {
      const path = ROUTE_PATHS[params.route];
      if (!path) throw new Error("未登记的展示页面");
      window.setTimeout(() => window.location.assign(path), 120);
      return { route: params.route, scheduled: true };
    }
    case "web.set_scene":
      setScene(params.scene);
      return { scene: params.scene };
    case "web.show_panel":
      setPanel(params.panel, true);
      return { panel: params.panel, visible: true };
    case "web.hide_panel":
      setPanel(params.panel, false);
      return { panel: params.panel, visible: false };
    case "web.set_text":
      setSceneText(params.field, params.text);
      return { field: params.field, updated: true };
    case "web.return_home":
      elements.scenePanel.hidden = true;
      setScene("welcome");
      if (!video.currentSrc.endsWith("/media/promo.mp4")) {
        video.src = "/media/promo.mp4";
        video.load();
      }
      video.currentTime = 0;
      return { home: true };
    case "video.load": {
      if (!/^\/media\/assets\/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(params.url || "")) {
        throw new Error("视频素材地址不在登记范围内");
      }
      video.pause();
      video.src = params.url;
      const loaded = new Promise((resolve, reject) => {
        const timer = window.setTimeout(() => reject(new Error("视频加载超时")), Math.max(100, Math.min(10000, timeoutMs - 100)));
        video.addEventListener("loadedmetadata", () => { window.clearTimeout(timer); resolve(); }, { once: true });
        video.addEventListener("error", () => { window.clearTimeout(timer); reject(new Error("无法读取登记的视频素材")); }, { once: true });
      });
      video.load();
      await loaded;
      return { duration_ms: Math.round(video.duration * 1000) };
    }
    case "video.play":
      await video.play();
      return { paused: video.paused };
    case "video.pause":
      video.pause();
      return { paused: video.paused };
    case "video.seek":
      return seekVideo(params.position_ms);
    case "video.set_volume":
      if (typeof params.volume !== "number" || params.volume < 0 || params.volume > 1) throw new Error("音量范围无效");
      video.volume = params.volume;
      return { volume: video.volume };
    case "video.mute":
      video.muted = true;
      return { muted: true };
    case "video.unmute":
      video.muted = false;
      return { muted: false };
    case "video.set_loop":
      video.loop = Boolean(params.enabled);
      return { loop: video.loop };
    default:
      throw new Error("展示页面不支持此动作");
  }
}

function connectDisplayCommands() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(protocol + "//" + window.location.host + "/ws/display");
  socket.addEventListener("message", async (message) => {
    try {
      const command = JSON.parse(message.data);
      if (command.type !== "command" || typeof command.run_id !== "string" || typeof command.command_id !== "string") return;
      const key = command.run_id + ":" + command.command_id;
      let response = displayCommandResults.get(key);
      if (!response) {
        let pending = pendingDisplayCommands.get(key);
        if (!pending) {
          pending = executeDisplayAction(command.action, command.params || {}, command.timeout_ms).then(
            (result) => ({ type: "ack", run_id: command.run_id, command_id: command.command_id, success: true, result }),
            (error) => ({ type: "ack", run_id: command.run_id, command_id: command.command_id, success: false, error: String(error.message || error).slice(0, 300) }),
          );
          pendingDisplayCommands.set(key, pending);
        }
        response = await pending;
        pendingDisplayCommands.delete(key);
        displayCommandResults.set(key, response);
        while (displayCommandResults.size > 128) displayCommandResults.delete(displayCommandResults.keys().next().value);
      }
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(response));
    } catch (error) {
      console.error("展示动作执行失败", error);
    }
  });
  socket.addEventListener("close", () => window.setTimeout(connectDisplayCommands, 1500));
}

elements.playButton.addEventListener("click", (event) => {
  event.stopPropagation();
  togglePlayback();
});
elements.video.addEventListener("playing", () => {
  elements.playButton.hidden = true;
});
elements.video.addEventListener("pause", () => {
  if (elements.video.currentTime > 0) {
    elements.playLabel.textContent = "继续播放";
    elements.playButton.hidden = false;
  }
});
elements.video.addEventListener("error", () => showFeedback("无法读取宣传片，请检查 media/company-promo.mp4"));
elements.fullscreenButton.addEventListener("click", async () => {
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else {
      await document.documentElement.requestFullscreen();
    }
  } catch (error) {
    showFeedback("此浏览器未能进入全屏");
  }
});
document.addEventListener("fullscreenchange", () => {
  const isFullscreen = Boolean(document.fullscreenElement);
  elements.fullscreenButton.setAttribute("aria-label", isFullscreen ? "退出全屏" : "进入全屏");
  elements.fullscreenButton.title = isFullscreen ? "退出全屏" : "全屏展示";
});

refreshStatus();
window.setInterval(refreshStatus, 1100);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshStatus();
});
connectEvents();
connectDisplayCommands();
