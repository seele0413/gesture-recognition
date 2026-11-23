/* Shared window navigation and event delivery; each page owns its feedback UI. */
(function () {
  "use strict";
  const flow = window.UsageFlow;
  window.name = flow.WINDOW_NAMES.admin;
  let disposed = false;
  let socket;
  let reconnect;
  const needsEvents = document.body.classList.contains("workflow-page")
    || document.body.classList.contains("settings-page");
  function showNavigationError(message) {
    const notice = document.querySelector("#validationMessage, #streamError, #pageStatus");
    if (!notice) return;
    notice.textContent = message;
    notice.dataset.state = "error";
    notice.dataset.kind = "error";
  }
  function connect() {
    if (disposed || !needsEvents) return;
    socket = new WebSocket((location.protocol === "https:" ? "wss:" : "ws:") + "//" + location.host + "/ws/events");
    socket.addEventListener("message", ({ data }) => {
      try {
        const event = JSON.parse(data);
        if (event.type === "gesture") console.log("[gesture-control]", event);
        document.dispatchEvent(new CustomEvent("usage-event", { detail: event }));
      } catch (error) { console.debug("运行事件读取失败", error); }
    });
    socket.addEventListener("close", () => { if (!disposed) reconnect = setTimeout(connect, 1500); });
  }
  document.addEventListener("click", (event) => {
    const link = event.target.closest("[data-open-display]");
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    try { flow.openWindow("display", "/"); }
    catch (error) { showNavigationError(error.message); }
  });
  window.addEventListener("pagehide", () => {
    disposed = true;
    clearTimeout(reconnect);
    socket?.close();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) { disposed = false; connect(); }
  });
  connect();
})();
