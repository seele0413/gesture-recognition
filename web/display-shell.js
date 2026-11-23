const elements = {
  frame: document.getElementById("displayPageFrame"),
  dot: document.getElementById("displayShellDot"),
  label: document.getElementById("displayShellLabel"),
};

const ROUTE_PATHS = Object.freeze({
  home: "/",
  settings: "/settings",
  workflows: "/workflows",
});
const DISPLAY_ORIGIN = window.location.origin;
const COMMAND_TIMEOUT_FALLBACK_MS = 10000;
const commandResults = new Map();
const pendingCommands = new Map();
const pendingPageCommands = new Map();

let pages = new Map();
let defaultPageId = null;
let currentPageId = null;
let pageGeneration = 0;
let pageReadyWaiter = null;
let displaySocket = null;
let eventSocket = null;
let displayReconnectTimer = 0;
let eventReconnectTimer = 0;
let displayBlocked = false;
let leaving = false;

function setShellStatus(state, message) {
  if (displayBlocked) {
    state = "error";
    message = "已有大屏窗口正在使用。请返回原窗口，或关闭原窗口后重试。";
  }
  elements.dot.dataset.state = state;
  elements.label.textContent = message;
}

document.getElementById("openManagement").addEventListener("click", (event) => {
  event.preventDefault();
  try { window.UsageFlow.openWindow("admin", "/settings"); }
  catch (error) { setShellStatus("error", error.message); }
});
document.getElementById("retryDisplay").addEventListener("click", () => {
  displayBlocked = false;
  document.getElementById("retryDisplay").hidden = true;
  connectDisplayCommands();
});

async function refreshControllerLabel() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) return;
    const status = await response.json();
    const view = window.UsageFlow.controllerView(status.controller);
    document.getElementById("displayControllerLabel").textContent = " · " + view.label;
  } catch (_error) { /* Connection state remains visible in the shell label. */ }
}

function sendDisplayState(type, payload = {}) {
  if (displaySocket?.readyState !== WebSocket.OPEN) return false;
  displaySocket.send(JSON.stringify({ type, ...payload }));
  return true;
}

function pageLabel(pageId) {
  return pages.get(pageId)?.title || pageId;
}

function isPublicExternalHost(hostname) {
  const host = String(hostname || "").toLowerCase().replace(/\.$/, "");
  if (!host || !host.includes(".") || host === "localhost"
      || /^(?:\d{1,3}\.){3}\d{1,3}$/.test(host) || host.includes(":")) return false;
  if ([".localhost", ".local", ".internal", ".test", ".invalid", ".example", ".home", ".lan"]
      .some((suffix) => host.endsWith(suffix))) return false;
  return host.split(".").every((label) =>
    /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)
  );
}

function safeExternalPageUrl(page) {
  if (!page || typeof page.url !== "string") return null;
  let url;
  try {
    url = new URL(page.url);
  } catch (_error) {
    return null;
  }
  if (url.protocol !== "https:" || url.username || url.password
      || (url.port && url.port !== "443") || !isPublicExternalHost(url.hostname)) return null;
  if (page.parent_id) {
    const parent = pages.get(page.parent_id);
    if (!parent || parent.page_type !== "external") return null;
    let parentUrl;
    try {
      parentUrl = new URL(parent.url);
    } catch (_error) {
      return null;
    }
    if (url.hostname.toLowerCase() !== parentUrl.hostname.toLowerCase()) return null;
  }
  return url;
}

function postToFrame(message) {
  if (!elements.frame.contentWindow) throw new Error("展示页面尚未创建");
  // External pages are display-only. Never send internal gesture/events or commands
  // to a third-party origin.
  if (pages.get(currentPageId)?.page_type === "external") return false;
  elements.frame.contentWindow.postMessage(message, DISPLAY_ORIGIN);
  return true;
}

function rejectPendingPageCommands(reason) {
  for (const pending of pendingPageCommands.values()) {
    window.clearTimeout(pending.timer);
    pending.reject(new Error(reason));
  }
  pendingPageCommands.clear();
}

function rejectPageReadyWaiter(reason) {
  if (!pageReadyWaiter) return;
  const waiter = pageReadyWaiter;
  pageReadyWaiter = null;
  window.clearTimeout(waiter.timer);
  waiter.reject(new Error(reason));
}

function navigatePage(pageId, timeoutMs = COMMAND_TIMEOUT_FALLBACK_MS) {
  const page = pages.get(pageId);
  if (!page) throw new Error("展示主页未登记：" + String(pageId));
  if (currentPageId === pageId && elements.frame.contentWindow) {
    return Promise.resolve({ page_id: pageId, title: page.title, changed: false });
  }

  const pageType = page.page_type || "local";
  let destination;
  if (pageType === "local") {
    const resolvedPath = new URL(page.path, DISPLAY_ORIGIN);
    if (typeof page.path !== "string"
        || !page.path.startsWith("/static/pages/")
        || resolvedPath.origin !== DISPLAY_ORIGIN
        || resolvedPath.pathname !== page.path
        || resolvedPath.search
        || resolvedPath.hash) {
      throw new Error("展示主页路径不在本地登记范围内");
    }
    destination = resolvedPath;
  } else if (pageType === "external") {
    const resolvedUrl = safeExternalPageUrl(page);
    if (!resolvedUrl) {
      throw new Error("外部展示网页未通过 HTTPS、公开域名或父页面域名校验");
    }
    destination = resolvedUrl;
  } else {
    throw new Error("不支持的展示页面类型");
  }

  rejectPageReadyWaiter("展示页面切换请求已被更新");
  rejectPendingPageCommands("展示页面正在切换，当前页面动作已中止");
  const generation = ++pageGeneration;
  currentPageId = null;
  setShellStatus("switching", "正在切换展示页面 · " + page.title);
  sendDisplayState("display:loading", { page_id: pageId, generation });

  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      if (pageReadyWaiter?.generation === generation) pageReadyWaiter = null;
      reject(new Error("展示页面加载超时：" + page.title));
      setShellStatus("error", "展示页面加载超时 · " + page.title);
    }, Math.max(1000, Math.min(30000, timeoutMs)));

    pageReadyWaiter = {
      generation,
      pageId,
      pageType,
      url: pageType === "external" ? destination.href : null,
      timer,
      resolve: () => {
        currentPageId = pageId;
        pageReadyWaiter = null;
        const readyNotified = sendDisplayState("display:ready", { page_id: pageId, generation });
        const connectedState = readyNotified ? "connected" : "connecting";
        setShellStatus(connectedState, pageType === "external"
          ? "外部网页导航已完成 · " + page.title
          : "展示控制中心 · " + page.title);
        resolve({
          page_id: pageId,
          title: page.title,
          changed: true,
          navigation_completed: pageType === "external",
          visual_verification_required: pageType === "external",
        });
      },
      reject,
    };

    if (pageType === "external") {
      elements.frame.referrerPolicy = "no-referrer";
      elements.frame.src = destination.href;
      return;
    }

    elements.frame.referrerPolicy = "same-origin";
    destination.searchParams.set("shell_generation", String(generation));
    elements.frame.src = destination.pathname + destination.search;
  });
}

function handleExternalFrameLoad() {
  const waiter = pageReadyWaiter;
  if (!waiter || waiter.pageType !== "external" || !waiter.url) return;
  if (elements.frame.src !== waiter.url) return;
  window.clearTimeout(waiter.timer);
  waiter.resolve();
}

function sendPageCommand(command, timeoutMs = COMMAND_TIMEOUT_FALLBACK_MS) {
  if (!currentPageId || !elements.frame.contentWindow) {
    return Promise.reject(new Error("当前没有已就绪的展示主页"));
  }
  if (pages.get(currentPageId)?.page_type === "external") {
    return Promise.reject(new Error("外部官网当前仅支持整页展示和页面切换，不支持内部动作"));
  }
  const key = command.run_id + ":" + command.command_id;
  if (pendingPageCommands.has(key)) return pendingPageCommands.get(key).promise;

  let resolvePromise;
  let rejectPromise;
  const promise = new Promise((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  const timer = window.setTimeout(() => {
    pendingPageCommands.delete(key);
    rejectPromise(new Error("展示页面执行动作超时"));
  }, Math.max(100, Math.min(30000, timeoutMs)));

  pendingPageCommands.set(key, {
    promise,
    resolve: resolvePromise,
    reject: rejectPromise,
    timer,
    generation: pageGeneration,
  });
  try {
    postToFrame({
      type: "display:command",
      generation: pageGeneration,
      command,
    });
  } catch (error) {
    pendingPageCommands.delete(key);
    window.clearTimeout(timer);
    rejectPromise(error);
  }
  return promise;
}

async function executeDisplayCommand(command) {
  const timeoutMs = Number.isInteger(command.timeout_ms) ? command.timeout_ms : COMMAND_TIMEOUT_FALLBACK_MS;
  switch (command.action) {
    case "web.navigate_page":
      return await navigatePage(command.params?.page_id, timeoutMs);
    case "web.navigate_route": {
      const path = ROUTE_PATHS[command.params?.route];
      if (!path) throw new Error("管理页面路由未登记");
      window.setTimeout(() => window.location.assign(path), 250);
      return { route: command.params.route, scheduled: true };
    }
    case "web.navigate_parent": {
      const currentPage = pages.get(currentPageId);
      const parentId = currentPage?.parent_id || defaultPageId;
      if (!parentId) throw new Error("当前页面没有可返回的父页面");
      if (parentId === currentPageId) {
        return { page_id: currentPageId, title: pageLabel(currentPageId), changed: false };
      }
      return await navigatePage(parentId, timeoutMs);
    }
    case "web.return_home":
      if (!defaultPageId) throw new Error("默认展示主页尚未初始化");
      if (currentPageId !== defaultPageId) {
        return await navigatePage(defaultPageId, timeoutMs);
      }
      if (pages.get(currentPageId)?.page_type === "external") {
        return { page_id: defaultPageId, title: pageLabel(defaultPageId), changed: false };
      }
      return await sendPageCommand(command, timeoutMs);
    default:
      return await sendPageCommand(command, timeoutMs);
  }
}

function sendCommandAck(socket, response) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(response));
}

async function handleDisplayCommand(socket, command) {
  if (!command || command.type !== "command"
      || typeof command.run_id !== "string"
      || typeof command.command_id !== "string"
      || typeof command.action !== "string") return;

  const key = command.run_id + ":" + command.command_id;
  const cached = commandResults.get(key);
  if (cached) {
    sendCommandAck(socket, cached);
    return;
  }
  if (pendingCommands.has(key)) {
    const existing = await pendingCommands.get(key);
    sendCommandAck(socket, existing);
    return;
  }

  const pending = (async () => {
    try {
      const result = await executeDisplayCommand(command);
      return { type: "ack", run_id: command.run_id, command_id: command.command_id, success: true, result };
    } catch (error) {
      return {
        type: "ack", run_id: command.run_id, command_id: command.command_id,
        success: false, error: String(error?.message || error).slice(0, 300),
      };
    }
  })();
  pendingCommands.set(key, pending);
  const response = await pending;
  pendingCommands.delete(key);
  commandResults.set(key, response);
  while (commandResults.size > 128) commandResults.delete(commandResults.keys().next().value);
  sendCommandAck(socket, response);
}

function handleFrameMessage(event) {
  if (pages.get(currentPageId)?.page_type === "external") return;
  if (event.origin !== DISPLAY_ORIGIN || event.source !== elements.frame.contentWindow) return;
  const message = event.data;
  if (!message || typeof message !== "object") return;

  if (message.type === "display:ready") {
    const waiter = pageReadyWaiter;
    if (!waiter || message.generation !== waiter.generation || message.page_id !== waiter.pageId) return;
    window.clearTimeout(waiter.timer);
    waiter.resolve();
    return;
  }

  if (message.type === "display:result") {
    const key = message.run_id + ":" + message.command_id;
    const pending = pendingPageCommands.get(key);
    if (!pending || pending.generation !== message.generation || message.generation !== pageGeneration) return;
    pendingPageCommands.delete(key);
    window.clearTimeout(pending.timer);
    if (message.success === true) pending.resolve(message.result && typeof message.result === "object" ? message.result : {});
    else pending.reject(new Error(String(message.error || "展示页面动作执行失败").slice(0, 300)));
  }
}

function connectDisplayCommands() {
  window.clearTimeout(displayReconnectTimer);
  if (leaving || displayBlocked || displaySocket) return;
  let accepted = false;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(protocol + "//" + window.location.host + "/ws/display");
  displaySocket = socket;
  socket.addEventListener("open", () => {
    if (displaySocket !== socket) return;
    accepted = true;
    window.name = window.UsageFlow.WINDOW_NAMES.display;
    if (pageReadyWaiter) {
      sendDisplayState("display:loading", {
        page_id: pageReadyWaiter.pageId,
        generation: pageReadyWaiter.generation,
      });
      setShellStatus("connecting", "展示控制中心已连接 · 等待展示页面就绪");
      return;
    }
    if (currentPageId) {
      sendDisplayState("display:ready", {
        page_id: currentPageId,
        generation: pageGeneration,
      });
      setShellStatus("connected", "展示控制中心已连接 · " + pageLabel(currentPageId));
      return;
    }
    setShellStatus("connecting", "展示控制中心已连接 · 等待展示页面就绪");
  });
  socket.addEventListener("message", (message) => {
    try {
      handleDisplayCommand(socket, JSON.parse(message.data)).catch((error) => {
        console.error("展示命令处理失败", error);
      });
    } catch (error) {
      console.error("无法解析展示命令", error);
    }
  });
  socket.addEventListener("close", async (event) => {
    if (displaySocket === socket) {
      displaySocket = null;
      if (leaving) return;
      // A close before accept is HTTP 403 in browsers and appears as 1006.
      // Check actual ownership instead of retrying a rejected second executor.
      let occupied = event.code === 1013;
      if (!accepted && !occupied) {
        try {
          const response = await fetch("/api/workflow-status", { cache: "no-store" });
          occupied = response.ok && (await response.json()).display_connected;
        } catch (_error) { /* A real server outage still reconnects. */ }
      }
      if (leaving || displaySocket) return;
      if (occupied) {
        displayBlocked = true;
        document.getElementById("retryDisplay").hidden = false;
        setShellStatus("error", "");
        return;
      }
      setShellStatus("connecting", "展示控制中心连接中断，正在重连");
      displayReconnectTimer = window.setTimeout(connectDisplayCommands, 1200);
    }
  });
  socket.addEventListener("error", () => socket.close());
}

function connectEvents() {
  window.clearTimeout(eventReconnectTimer);
  if (leaving || eventSocket) return;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(protocol + "//" + window.location.host + "/ws/events");
  eventSocket = socket;
  socket.addEventListener("open", refreshControllerLabel);
  socket.addEventListener("message", (message) => {
    try {
      const event = JSON.parse(message.data);
      if (event.type === "gesture") console.log("[gesture-control]", event);
      if (event.type === "controller" || event.type === "stream") refreshControllerLabel();
      postToFrame({ type: "display:event", event, generation: pageGeneration });
    } catch (error) {
      if (error?.message) console.debug("当前展示页尚未就绪", error.message);
    }
  });
  socket.addEventListener("close", () => {
    if (eventSocket === socket) {
      eventSocket = null;
      if (leaving) return;
      eventReconnectTimer = window.setTimeout(connectEvents, 1500);
    }
  });
  socket.addEventListener("error", () => socket.close());
}

window.addEventListener("message", handleFrameMessage);
elements.frame.addEventListener("load", handleExternalFrameLoad);

async function initializeDisplayShell() {
  try {
    const response = await fetch("/api/display/pages", { cache: "no-store" });
    if (!response.ok) throw new Error("无法读取展示主页登记表");
    const payload = await response.json();
    if (!Array.isArray(payload.pages)) throw new Error("展示主页登记表格式无效");
    const externalPages = [];
    for (const page of payload.pages) {
      if (!page || typeof page.page_id !== "string" || typeof page.title !== "string"
          || page.enabled === false || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(page.page_id)) continue;
      const pageType = page.page_type || "local";
      if (pageType === "local" && typeof page.path === "string" && page.path.startsWith("/static/pages/")) {
        pages.set(page.page_id, page);
      } else if (pageType === "external") {
        externalPages.push(page);
      }
    }

    // Register external roots first, then children once their registered parent is present.
    // The server only returns enabled database records; the browser independently verifies
    // HTTPS/public-host rules and same-host parent relationships before allowing navigation.
    let pending = externalPages;
    while (pending.length) {
      let progressed = false;
      const nextPending = [];
      for (const page of pending) {
        if (page.parent_id && !pages.has(page.parent_id)) {
          nextPending.push(page);
          continue;
        }
        if (safeExternalPageUrl(page)) pages.set(page.page_id, page);
        progressed = true;
      }
      if (!progressed) break;
      pending = nextPending;
    }
    defaultPageId = payload.default_page_id;
    if (typeof defaultPageId !== "string" || !pages.has(defaultPageId)) {
      throw new Error("默认展示主页未在白名单中登记");
    }
    connectDisplayCommands();
    connectEvents();
    await navigatePage(defaultPageId);
  } catch (error) {
    setShellStatus("error", String(error?.message || error));
    console.error("展示控制中心初始化失败", error);
  }
}

window.addEventListener("pagehide", () => {
  leaving = true;
  window.clearTimeout(displayReconnectTimer);
  window.clearTimeout(eventReconnectTimer);
  rejectPageReadyWaiter("展示控制中心已离开页面");
  rejectPendingPageCommands("展示控制中心已离开页面");
  if (displaySocket) displaySocket.close();
  if (eventSocket) eventSocket.close();
  displaySocket = null;
  eventSocket = null;
});

window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  leaving = false;
  connectDisplayCommands();
  connectEvents();
});

initializeDisplayShell();
