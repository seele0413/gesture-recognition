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
let feedLoaded = false;

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
  // MJPEG is a long-lived multipart image; some browsers do not reliably fire
  // the initial load event, so also observe its decoded intrinsic dimensions.
  if (status.state === "running" && elements.cameraFeed.getAttribute("src")
      && !feedFailed && elements.cameraFeed.naturalWidth > 0) {
    feedLoaded = true;
  }
  const controller = status.controller || { state: "unlocked", track_id: null };
  const streamReady = status.state === "running";
  const frameFresh = Boolean(status.frame_fresh ?? status.frame_ready);
  const hasImage = streamReady && frameFresh && feedLoaded && elements.cameraFeed.naturalWidth > 0 && !feedFailed;

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
      : !feedLoaded ? "正在加载摄像头画面"
        : status.frame_age_ms == null ? "已连接，正在等待首帧" : "画面停滞，正在等待新帧";
    elements.cameraStatusLabel.textContent = feedFailed
      ? "MJPEG 预览连接失败，正在自动重订阅"
      : !feedLoaded ? "摄像头已连接，正在接收画面"
        : status.frame_age_ms == null
          ? "摄像头已连接，等待视频帧"
          : "视频帧已停滞 " + (status.frame_age_ms / 1000).toFixed(1) + " 秒";
    elements.cameraStatus.dataset.state = "stale";
    return;
  }

  if (controller.state === "locked") {
    elements.cameraStatusLabel.textContent = "主控已锁定";
    elements.cameraStatus.dataset.state = "locked";
  } else if (controller.state === "lost") {
    elements.cameraStatusLabel.textContent = "主控暂时丢失 · 控制暂停";
    elements.cameraStatus.dataset.state = "lost";
  } else {
    elements.cameraStatusLabel.textContent = "等待 OK 手势锁定";
    elements.cameraStatus.dataset.state = "running";
  }
}

function syncCameraFeed() {
  if (status.state === "running") {
    if (!elements.cameraFeed.getAttribute("src")) {
      feedFailed = false;
      feedLoaded = false;
      elements.cameraFeed.src = "/video.mjpg?display=" + Date.now();
    }
  } else {
    window.clearTimeout(feedRetryTimer);
    feedFailed = false;
    feedLoaded = false;
    elements.cameraFeed.removeAttribute("src");
  }
  renderCamera();
}

elements.cameraFeed.addEventListener("error", () => {
  if (status.state !== "running") return;
  feedFailed = true;
  feedLoaded = false;
  renderCamera();
  window.clearTimeout(feedRetryTimer);
  feedRetryTimer = window.setTimeout(() => {
    if (status.state !== "running") return;
    elements.cameraFeed.removeAttribute("src");
    elements.cameraFeed.src = "/video.mjpg?display=" + Date.now();
  }, 1200);
});

elements.cameraFeed.addEventListener("load", () => {
  feedFailed = false;
  feedLoaded = elements.cameraFeed.naturalWidth > 0;
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
  if (event.action_triggered) applyAction(event.action);
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
