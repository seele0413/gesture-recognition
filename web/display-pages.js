const elements = {
  connection: document.getElementById("pageConnection"),
  connectionLabel: document.getElementById("pageConnectionLabel"),
  status: document.getElementById("pageStatus"),
  count: document.getElementById("pageCount"),
  tree: document.getElementById("pageTree"),
  add: document.getElementById("addPage"),
  dialog: document.getElementById("pageDialog"),
  form: document.getElementById("pageForm"),
  dialogTitle: document.getElementById("pageDialogTitle"),
  pageId: document.getElementById("pageId"),
  title: document.getElementById("pageTitle"),
  url: document.getElementById("pageUrl"),
  parent: document.getElementById("pageParent"),
  description: document.getElementById("pageDescription"),
  enabled: document.getElementById("pageEnabled"),
  urlFeedback: document.getElementById("urlFeedback"),
  formError: document.getElementById("pageFormError"),
  validateUrl: document.getElementById("validatePageUrl"),
  save: document.getElementById("savePage"),
  cancel: document.getElementById("cancelPageDialog"),
  close: document.getElementById("closePageDialog"),
};

let pages = [];
let defaultPageId = "promo";
let editingPageId = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail) ? payload.detail.join("；") : payload.detail;
    throw new Error(detail || "请求失败，请检查服务状态");
  }
  return payload;
}

function setStatus(message, kind = "info") {
  elements.status.textContent = message;
  elements.status.dataset.kind = kind;
}

function setConnection(message, state = "stopped") {
  elements.connection.dataset.state = state;
  elements.connectionLabel.textContent = message;
}

function makeButton(label, handler, extraClass = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "page-action" + (extraClass ? " " + extraClass : "");
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

function descendantsOf(pageId) {
  const found = new Set();
  const visit = (parentId) => {
    for (const page of pages) {
      if (page.parent_id === parentId && !found.has(page.page_id)) {
        found.add(page.page_id);
        visit(page.page_id);
      }
    }
  };
  visit(pageId);
  return found;
}

function fillParentOptions(selectedId = "", excludedIds = new Set()) {
  elements.parent.replaceChildren();
  const rootOption = document.createElement("option");
  rootOption.value = "";
  rootOption.textContent = "作为独立主页";
  elements.parent.append(rootOption);
  const candidates = pages
    .filter((page) => page.page_type === "external" && page.page_id !== editingPageId
      && !excludedIds.has(page.page_id)
      && (page.enabled || page.page_id === selectedId))
    .sort((a, b) => a.title.localeCompare(b.title, "zh-CN"));
  for (const page of candidates) {
    const option = document.createElement("option");
    option.value = page.page_id;
    option.disabled = !page.enabled;
    option.textContent = page.title + " · " + page.page_id
      + (page.enabled ? "" : "（已停用，仅保留当前父级关系）");
    elements.parent.append(option);
  }
  elements.parent.value = selectedId || "";
}

function renderPageNode(page, childrenByParent, visited = new Set()) {
  if (visited.has(page.page_id)) return document.createElement("li");
  const nextVisited = new Set(visited);
  nextVisited.add(page.page_id);
  const item = document.createElement("li");
  item.className = "page-node";

  const card = document.createElement("article");
  card.className = "page-node-card";
  const main = document.createElement("div");
  main.className = "page-node-main";
  const titleRow = document.createElement("div");
  titleRow.className = "page-node-title-row";
  const title = document.createElement("strong");
  title.className = "page-node-title";
  title.textContent = page.title;
  titleRow.append(title);

  const tag = (label, kind = "") => {
    const badge = document.createElement("span");
    badge.className = "page-tag";
    if (kind) badge.dataset.kind = kind;
    badge.textContent = label;
    titleRow.append(badge);
  };
  if (page.page_id === defaultPageId) tag("默认主页", "default");
  tag(page.enabled ? "工作流可调用" : "工作流不可调用", page.enabled ? "available" : "disabled");
  tag(page.page_type === "local" ? "内置页面" : "外部网页");
  if (page.page_type === "external") tag("嵌入兼容性待现场验证", "pending");

  const meta = document.createElement("div");
  meta.className = "page-node-meta";
  meta.textContent = page.page_id + (page.description ? " · " + page.description : "");
  const url = document.createElement("a");
  url.className = "page-node-url page-node-meta";
  url.href = page.url || page.path || "#";
  url.textContent = page.url || page.path || "";
  if (page.page_type === "external") {
    url.target = "_blank";
    url.rel = "noopener noreferrer";
  }
  main.append(titleRow, meta, url);

  const actions = document.createElement("div");
  actions.className = "page-node-actions";
  if (page.page_type === "external") {
    actions.append(makeButton("编辑", () => openEditor(page)));
  }
  if (page.enabled && page.page_id !== defaultPageId) {
    actions.append(makeButton("设为默认", () => setDefault(page.page_id), "page-action-primary"));
  }
  if (page.page_type === "external") {
    actions.append(makeButton(page.enabled ? "停用" : "启用", () => toggleEnabled(page), ""));
    actions.append(makeButton("删除", () => deletePage(page), "page-action-danger"));
  }
  card.append(main, actions);
  item.append(card);

  const children = childrenByParent.get(page.page_id) || [];
  if (children.length) {
    const list = document.createElement("ul");
    for (const child of children) list.append(renderPageNode(child, childrenByParent, nextVisited));
    item.append(list);
  }
  return item;
}

function renderPages() {
  elements.tree.replaceChildren();
  elements.count.textContent = pages.length + " 个页面";
  if (!pages.length) {
    const empty = document.createElement("p");
    empty.className = "page-empty";
    empty.textContent = "还没有登记展示页面。点击右上角「添加网页」开始。";
    elements.tree.append(empty);
    return;
  }
  const childrenByParent = new Map();
  for (const page of pages) {
    const key = page.parent_id || "";
    if (!childrenByParent.has(key)) childrenByParent.set(key, []);
    childrenByParent.get(key).push(page);
  }
  for (const children of childrenByParent.values()) {
    children.sort((a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title, "zh-CN"));
  }
  const roots = childrenByParent.get("") || [];
  const list = document.createElement("ul");
  for (const page of roots) list.append(renderPageNode(page, childrenByParent));
  elements.tree.append(list);
}

async function loadPages() {
  setConnection("正在读取网页", "connecting");
  try {
    const payload = await api("/api/display/pages?include_disabled=true");
    pages = Array.isArray(payload.pages) ? payload.pages : [];
    defaultPageId = payload.default_page_id || "promo";
    renderPages();
    setConnection("网页目录已加载", "running");
    setStatus("已读取 " + pages.length + " 个登记页面。新增或修改页面后，工作流动作选项会动态更新。", "success");
  } catch (error) {
    setConnection("读取失败", "error");
    setStatus(error.message, "error");
    elements.tree.replaceChildren();
    const empty = document.createElement("p");
    empty.className = "page-empty";
    empty.textContent = "无法读取网页目录，请确认本地服务正在运行后刷新。";
    elements.tree.append(empty);
  }
}

function openEditor(page = null) {
  editingPageId = page?.page_id || null;
  elements.form.reset();
  elements.formError.textContent = "";
  elements.urlFeedback.textContent = "";
  elements.dialogTitle.textContent = page ? "编辑展示网页" : "添加展示网页";
  elements.pageId.readOnly = Boolean(page);
  elements.pageId.value = page?.page_id || "";
  elements.title.value = page?.title || "";
  elements.url.value = page?.url || "";
  elements.description.value = page?.description || "";
  elements.enabled.checked = page ? Boolean(page.enabled) : true;
  const excluded = page ? descendantsOf(page.page_id) : new Set();
  fillParentOptions(page?.parent_id || "", excluded);
  elements.dialog.showModal();
  (page ? elements.title : elements.pageId).focus();
}

async function validateUrl() {
  elements.urlFeedback.textContent = "正在检测地址格式…";
  try {
    const result = await api("/api/display/pages/validate-url", {
      method: "POST",
      body: JSON.stringify({ url: elements.url.value.trim() }),
    });
    elements.url.value = result.url;
    elements.urlFeedback.textContent = "HTTPS 地址格式有效，域名：" + result.hostname
      + "。这不代表目标网站允许 iframe 嵌入。";
  } catch (error) {
    elements.urlFeedback.textContent = error.message;
  }
}

async function savePage(event) {
  event.preventDefault();
  elements.formError.textContent = "";
  const pageId = editingPageId || elements.pageId.value.trim();
  const payload = {
    title: elements.title.value.trim(),
    url: elements.url.value.trim(),
    description: elements.description.value.trim(),
    parent_id: elements.parent.value || null,
    enabled: elements.enabled.checked,
  };
  if (!editingPageId) payload.page_id = pageId;
  elements.save.disabled = true;
  try {
    const path = editingPageId
      ? "/api/display/pages/" + encodeURIComponent(editingPageId)
      : "/api/display/pages";
    const method = editingPageId ? "PUT" : "POST";
    await api(path, { method, body: JSON.stringify(payload) });
    elements.dialog.close();
    await loadPages();
    setStatus((editingPageId ? "已更新页面：" : "已添加页面：") + payload.title, "success");
  } catch (error) {
    elements.formError.textContent = error.message;
  } finally {
    elements.save.disabled = false;
  }
}

async function setDefault(pageId) {
  try {
    await api("/api/display/default", { method: "POST", body: JSON.stringify({ page_id: pageId }) });
    await loadPages();
    setStatus("默认展示主页已设置为：" + (pages.find((page) => page.page_id === pageId)?.title || pageId), "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function toggleEnabled(page) {
  try {
    await api("/api/display/pages/" + encodeURIComponent(page.page_id), {
      method: "PUT", body: JSON.stringify({ enabled: !page.enabled }),
    });
    await loadPages();
    setStatus((page.enabled ? "已停用：" : "已启用：") + page.title, "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function deletePage(page) {
  if (!window.confirm("确定删除「" + page.title + "」的登记信息吗？不会删除目标网站本身。")) return;
  try {
    await api("/api/display/pages/" + encodeURIComponent(page.page_id), { method: "DELETE" });
    await loadPages();
    setStatus("已删除页面登记：" + page.title, "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

elements.add.addEventListener("click", () => openEditor());
elements.form.addEventListener("submit", savePage);
elements.validateUrl.addEventListener("click", validateUrl);
elements.cancel.addEventListener("click", () => elements.dialog.close());
elements.close.addEventListener("click", () => elements.dialog.close());
elements.url.addEventListener("input", () => { elements.urlFeedback.textContent = ""; });
loadPages();
