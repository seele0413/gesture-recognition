const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const source = fs.readFileSync(path.join(root, "web/display-pages.js"), "utf8");

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.value = "";
    this.textContent = "";
    this.className = "";
    this.checked = false;
    this.disabled = false;
    this.readOnly = false;
    this.open = false;
  }

  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = [...items]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  reset() {}
}

function walk(node, visit) {
  visit(node);
  for (const child of node.children || []) walk(child, visit);
}

async function createHarness(initialPages) {
  const ids = [
    "pageConnection", "pageConnectionLabel", "pageStatus", "pageCount", "pageTree",
    "addPage", "pageDialog", "pageForm", "pageDialogTitle", "pageId", "pageTitle",
    "pageUrl", "pageParent", "pageDescription", "pageEnabled", "urlFeedback",
    "pageFormError", "validatePageUrl", "savePage", "cancelPageDialog", "closePageDialog",
  ];
  const elements = new Map(ids.map((id) => [id, new FakeElement(id)]));
  const pages = initialPages.map((page) => ({ ...page }));
  const requests = [];
  const document = {
    getElementById(id) { return elements.get(id); },
    createElement(tagName) { return new FakeElement(tagName); },
  };
  const fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url === "/api/display/pages?include_disabled=true") {
      return { ok: true, json: async () => ({ pages, default_page_id: "promo" }) };
    }
    if (url.startsWith("/api/display/pages/") && options.method === "PUT") {
      const pageId = decodeURIComponent(url.split("/").pop());
      const changes = JSON.parse(options.body);
      const index = pages.findIndex((page) => page.page_id === pageId);
      Object.assign(pages[index], changes);
      return { ok: true, json: async () => ({ page: pages[index] }) };
    }
    throw new Error("Unexpected test request: " + url + " " + (options.method || "GET"));
  };
  vm.runInNewContext(source, { document, fetch, window: { confirm: () => true } });
  await new Promise((resolve) => setImmediate(resolve));
  return { elements, pages, requests };
}

const pageFixtures = [
  { page_id: "promo", title: "企业宣传片", description: "", page_type: "local",
    path: "/static/pages/promo.html", url: null, parent_id: null, enabled: true, sort_order: 0 },
  { page_id: "company_website", title: "康晋电气官网", description: "", page_type: "external",
    path: null, url: "https://www.zhcomking.com/", parent_id: null, enabled: true, sort_order: 1 },
  { page_id: "disabled_parent", title: "已停用父页面", description: "", page_type: "external",
    path: null, url: "https://www.zhcomking.com/catalog/", parent_id: null, enabled: false, sort_order: 2 },
  { page_id: "disabled_child", title: "已停用子页面", description: "", page_type: "external",
    path: null, url: "https://www.zhcomking.com/catalog/product/", parent_id: "disabled_parent",
    enabled: false, sort_order: 3 },
];

test("page manager renders workflow and iframe verification states separately", async () => {
  const { elements } = await createHarness(pageFixtures);
  const labels = [];
  walk(elements.get("pageTree"), (node) => {
    if (node.textContent) labels.push(node.textContent);
  });
  assert.ok(labels.includes("工作流可调用"));
  assert.ok(labels.includes("工作流不可调用"));
  assert.ok(labels.includes("嵌入兼容性待现场验证"));
});

test("editing a disabled child preserves its disabled parent in the submitted form", async () => {
  const { elements, requests } = await createHarness(pageFixtures);
  let childItem = null;
  walk(elements.get("pageTree"), (node) => {
    if (node.className === "page-node") {
      let title = "";
      walk(node, (nested) => {
        if (nested.className === "page-node-title") title = nested.textContent;
      });
      if (title === "已停用子页面") childItem = node;
    }
  });
  assert.ok(childItem, "disabled child should appear in the hierarchy");

  let editButton = null;
  walk(childItem, (node) => {
    if (node.tagName === "button" && node.textContent === "编辑") editButton = node;
  });
  assert.ok(editButton, "external page should expose an edit action");
  editButton.listeners.click();

  const parentSelect = elements.get("pageParent");
  assert.equal(parentSelect.value, "disabled_parent");
  const retainedOption = parentSelect.children.find((option) => option.value === "disabled_parent");
  assert.ok(retainedOption);
  assert.equal(retainedOption.disabled, true);
  assert.match(retainedOption.textContent, /仅保留当前父级关系/);

  elements.get("pageTitle").value = "编辑后的子页面";
  await elements.get("pageForm").listeners.submit({ preventDefault() {} });
  const update = requests.find((request) =>
    request.url === "/api/display/pages/disabled_child" && request.options.method === "PUT"
  );
  assert.ok(update, "edit should submit an update request");
  assert.equal(JSON.parse(update.options.body).parent_id, "disabled_parent");
});
