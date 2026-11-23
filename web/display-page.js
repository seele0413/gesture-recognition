const pageId = document.body.dataset.pageId;
const generation = Number(new URLSearchParams(window.location.search).get("shell_generation") || 0);
const fields = {
  headline: document.getElementById("pageHeadline"),
  subhead: document.getElementById("pageSubhead"),
  notice: document.getElementById("pageNotice"),
};
const status = document.getElementById("pageStatus");
const defaultCopy = {
  factory: { headline: "智能制造", subhead: "工厂与制造流程展示" },
  product: { headline: "产品中心", subhead: "电气产品展示" },
};

function postResult(command, success, result, error) {
  window.parent.postMessage({
    type: "display:result",
    generation,
    run_id: command.run_id,
    command_id: command.command_id,
    success,
    result: result || {},
    error: error || "",
  }, window.location.origin);
}

function setPanel(panel, visible) {
  const target = document.querySelector('[data-panel="' + CSS.escape(panel) + '"]');
  if (!target) throw new Error("当前展示主页没有登记面板：" + panel);
  target.hidden = !visible;
  return { panel, visible };
}

function executeDisplayAction(action, params) {
  switch (action) {
    case "web.set_scene": {
      const scenes = {
        welcome: "welcome", company_intro: "company",
        product_intro: "product", factory_intro: "factory",
        presentation_mode: "presentation",
      };
      const panel = scenes[params.scene];
      if (!panel) throw new Error("展厅场景未登记");
      return setPanel(panel, true);
    }
    case "web.show_panel":
      return setPanel(params.panel, true);
    case "web.hide_panel":
      return setPanel(params.panel, false);
    case "web.set_text": {
      const target = fields[params.field];
      if (!target || typeof params.text !== "string" || params.text.length > 160) {
        throw new Error("展示文本字段或长度无效");
      }
      target.textContent = params.text;
      return { field: params.field, updated: true };
    }
    default:
      throw new Error("当前展示主页不支持动作：" + action);
  }
}

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin || event.source !== window.parent) return;
  const message = event.data;
  if (!message || typeof message !== "object") return;

  if (message.type === "display:event") {
    const eventData = message.event;
    if (eventData?.type === "controller" && status) {
      status.textContent = window.UsageFlow.controllerView(eventData).label;
    }
    return;
  }

  if (message.type !== "display:command" || message.generation !== generation) return;
  const command = message.command;
  if (!command || typeof command.run_id !== "string" || typeof command.command_id !== "string") return;
  try {
    const result = executeDisplayAction(command.action, command.params || {});
    postResult(command, true, result);
  } catch (error) {
    postResult(command, false, {}, String(error?.message || error).slice(0, 300));
  }
});

window.parent.postMessage({ type: "display:ready", page_id: pageId, generation }, window.location.origin);
fetch("/api/status", { cache: "no-store" }).then((response) => response.json()).then((snapshot) => {
  if (status) status.textContent = window.UsageFlow.controllerView(snapshot.controller).label;
}).catch(() => {});
