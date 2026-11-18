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

function findPageNode(tree, titleText) {
  let result = null;
  walk(tree, (node) => {
    if (node.className !== "page-node") return;
    let title = "";
    walk(node, (nested) => {
      if (nested.className === "page-node-title") title = nested.textContent;
    });
    if (title === titleText) result = node;
  });
  return result;
}

function findButton(node, label) {
  let result = null;
  walk(node, (child) => {
    if (child.tagName === "button" && child.textContent === label) result = child;
  });
  return result;
}

function labelsIn(node) {
  const labels = [];
  walk(node, (child) => {
    if (child.textContent) labels.push(child.textContent);
  });
  return labels;
}

async function createHarness(initialPages, initialDefaultPageId = "promo") {
  const ids = [
    "pageConnection", "pageConnectionLabel", "pageStatus", "pageCount", "pageTree",
    "addPage", "pageDialog", "pageForm", "pageDialogTitle", "pageId", "pageTitle",
    "pageUrl", "pageParent", "pageDescription", "pageEnabled", "urlFeedback",
    "pageFormError", "validatePageUrl", "savePage", "cancelPageDialog", "closePageDialog",
  ];
  const elements = new Map(ids.map((id) => [id, new FakeElement(id)]));
  const state = {
    pages: initialPages.map((page) => ({ ...page })),
    defaultPageId: initialDefaultPageId,
  };
  const requests = [];
  const fetch = async (url, options = {}) => {
    requests.push({ url, options });
    const method = options.method || "GET";

    if (url === "/api/display/pages?include_disabled=true" && method === "GET") {
      return {
        ok: true,
        json: async () => ({ pages: state.pages, default_page_id: state.defaultPageId }),
      };
    }
    if (url === "/api/display/pages/validate-url" && method === "POST") {
      const payload = JSON.parse(options.body);
      const parsed = new URL(payload.url);
      return {
        ok: true,
        json: async () => ({
          valid: true,
          url: parsed.toString(),
          hostname: parsed.hostname,
        }),
      };
    }
    if (url === "/api/display/pages" && method === "POST") {
      const payload = JSON.parse(options.body);
      const page = {
        ...payload,
        path: null,
        page_type: "external",
        sort_order: state.pages.length,
      };
      state.pages.push(page);
      return { ok: true, json: async () => ({ page }) };
    }
    if (url === "/api/display/default" && method === "POST") {
      state.defaultPageId = JSON.parse(options.body).page_id;
      return {
        ok: true,
        json: async () => ({ default_page_id: state.defaultPageId }),
      };
    }
    if (url.startsWith("/api/display/pages/")) {
      const pageId = decodeURIComponent(url.split("/").pop());
      const index = state.pages.findIndex((page) => page.page_id === pageId);
      if (index < 0) {
        return { ok: false, json: async () => ({ detail: "展示页面不存在" }) };
      }
      if (method === "PUT") {
        const changes = JSON.parse(options.body);
        Object.assign(state.pages[index], changes);
        return { ok: true, json: async () => ({ page: state.pages[index] }) };
      }
      if (method === "DELETE") {
        state.pages.splice(index, 1);
        return { ok: true, json: async () => ({ deleted: true }) };
      }
    }
    throw new Error("Unexpected test request: " + url + " " + method);
  };
  const document = {
    getElementById(id) { return elements.get(id); },
    createElement(tagName) { return new FakeElement(tagName); },
  };
  vm.runInNewContext(source, {
    document,
    fetch,
    window: { confirm: () => true },
  });
  await new Promise((resolve) => setImmediate(resolve));
  return { elements, pages: state.pages, requests, state };
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
  const labels = labelsIn(elements.get("pageTree"));
  assert.ok(labels.includes("工作流可调用"));
  assert.ok(labels.includes("工作流不可调用"));
  assert.ok(labels.includes("嵌入兼容性待现场验证"));
});

test("editing a disabled child preserves its disabled parent in the submitted form", async () => {
  const { elements, requests } = await createHarness(pageFixtures);
  const childItem = findPageNode(elements.get("pageTree"), "已停用子页面");
  assert.ok(childItem, "disabled child should appear in the hierarchy");

  const editButton = findButton(childItem, "编辑");
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

test("built-in local pages can be selected as the default page", async () => {
  const { elements, requests, state } = await createHarness(pageFixtures, "company_website");
  const promoNode = findPageNode(elements.get("pageTree"), "企业宣传片");
  assert.ok(promoNode, "built-in promo page should be rendered");

  const makeDefault = findButton(promoNode, "设为默认");
  assert.ok(makeDefault, "enabled local pages should expose the default-page action");
  await makeDefault.listeners.click();

  const request = requests.find((item) =>
    item.url === "/api/display/default" && item.options.method === "POST"
  );
  assert.ok(request, "selecting a local default should call the default-page API");
  assert.equal(JSON.parse(request.options.body).page_id, "promo");
  assert.equal(state.defaultPageId, "promo");

  const updatedPromo = findPageNode(elements.get("pageTree"), "企业宣传片");
  assert.ok(labelsIn(updatedPromo).includes("默认主页"));
  const website = findPageNode(elements.get("pageTree"), "康晋电气官网");
  assert.ok(!labelsIn(website).includes("默认主页"));
});

test("page manager creates, edits, disables, and deletes an external page", async () => {
  const { elements, requests, state } = await createHarness(pageFixtures.slice(0, 2));

  elements.get("addPage").listeners.click();
  assert.equal(elements.get("pageDialog").open, true);
  elements.get("pageId").value = "energy_storage";
  elements.get("pageTitle").value = "储能系列";
  elements.get("pageUrl").value = "https://www.zhcomking.com/products/energy-storage/";
  elements.get("pageDescription").value = "储能产品展示";
  elements.get("pageParent").value = "company_website";
  elements.get("pageEnabled").checked = true;
  await elements.get("pageForm").listeners.submit({ preventDefault() {} });

  let page = state.pages.find((item) => item.page_id === "energy_storage");
  assert.ok(page, "new page should be added to the page directory");
  assert.equal(page.parent_id, "company_website");
  assert.equal(page.page_type, "external");
  assert.equal(elements.get("pageDialog").open, false);

  let pageNode = findPageNode(elements.get("pageTree"), "储能系列");
  assert.ok(pageNode, "new page should appear below its parent");
  findButton(pageNode, "编辑").listeners.click();
  elements.get("pageTitle").value = "储能产品中心";
  elements.get("pageDescription").value = "已更新的储能产品说明";
  await elements.get("pageForm").listeners.submit({ preventDefault() {} });

  page = state.pages.find((item) => item.page_id === "energy_storage");
  assert.equal(page.title, "储能产品中心");
  assert.equal(page.description, "已更新的储能产品说明");

  pageNode = findPageNode(elements.get("pageTree"), "储能产品中心");
  await findButton(pageNode, "停用").listeners.click();
  page = state.pages.find((item) => item.page_id === "energy_storage");
  assert.equal(page.enabled, false);

  pageNode = findPageNode(elements.get("pageTree"), "储能产品中心");
  await findButton(pageNode, "删除").listeners.click();
  assert.ok(!state.pages.some((item) => item.page_id === "energy_storage"));

  const methods = requests
    .filter((item) => item.url.includes("energy_storage") || item.url === "/api/display/pages")
    .map((item) => item.options.method || "GET");
  assert.ok(methods.includes("POST"));
  assert.ok(methods.includes("PUT"));
  assert.ok(requests.some((item) =>
    item.url === "/api/display/pages/energy_storage" && item.options.method === "DELETE"
  ));
});

test("URL validation displays the server-normalized HTTPS destination", async () => {
  const { elements, requests } = await createHarness(pageFixtures);
  elements.get("pageUrl").value = "https://WWW.ZHCOMKING.COM/products/";
  await elements.get("validatePageUrl").listeners.click();

  const request = requests.find((item) =>
    item.url === "/api/display/pages/validate-url" && item.options.method === "POST"
  );
  assert.ok(request);
  assert.equal(JSON.parse(request.options.body).url, "https://WWW.ZHCOMKING.COM/products/");
  assert.equal(
    elements.get("pageUrl").value,
    "https://www.zhcomking.com/products/",
  );
  assert.match(elements.get("urlFeedback").textContent, /不代表目标网站允许 iframe 嵌入/);
});
