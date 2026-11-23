(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.UsageFlow = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const WINDOW_NAMES = { display: "gesture-control-display", admin: "gesture-control-admin" };
  const GESTURE_LABELS = {
    Open_Palm: "张开手掌", Closed_Fist: "握拳", Thumb_Up: "竖拇指",
    Thumb_Down: "拇指向下", Pointing_Up: "食指向上", Victory: "比耶", ILoveYou: "我爱你手势",
  };
  function lockPrompt(controller = {}) {
    return "保持比耶手势 · " + (controller.lock_progress || 0) + "/"
      + (controller.lock_required_frames ?? 2) + "（最近 " + (controller.lock_window_frames ?? 5) + " 帧）";
  }
  function controllerView(controller = {}) {
    switch (controller.state) {
      case "locked": return { kind: "ready", label: "主控已锁定", detail: "主控轨迹有效，可进行手势操作" };
      case "suspect": return controller.identity_confirmed === true
        ? { kind: "ready", label: "原主控手部已确认", detail: "人体短暂漏检，可继续操作" }
        : { kind: "waiting", label: "身份待确认 · 控制暂停", detail: "正在确认原主控手部，不接受其他人接管" };
      case "reacquiring": case "lost":
        return { kind: "waiting", label: "正在寻找原主控 · 控制暂停", detail: "保留原主控会话，等待恢复或超时解锁" };
      default: return { kind: "waiting", label: "等待比耶锁定", detail: lockPrompt(controller) };
    }
  }
  function fingerprint(definition) {
    if (!definition) return "";
    const ignored = new Set(["id", "version", "enabled", "created_at", "updated_at"]);
    function sort(value, top = false) {
      if (Array.isArray(value)) return value.map((item) => sort(item));
      if (!value || typeof value !== "object") return value;
      return Object.fromEntries(Object.keys(value).sort()
        .filter((key) => !top || !ignored.has(key)).map((key) => [key, sort(value[key])]));
    }
    return JSON.stringify(sort(definition, true));
  }
  class DraftState {
    constructor() { this.baseline = ""; }
    saved(definition) { this.baseline = fingerprint(definition); }
    dirty(definition, isDraft = false) {
      return Boolean(definition) && (isDraft || fingerprint(definition) !== this.baseline);
    }
    async canLeave(definition, isDraft, choose, save) {
      if (!this.dirty(definition, isDraft)) return true;
      const choice = await choose();
      if (choice === "discard") return true;
      if (choice !== "save") return false;
      await save(); // A rejected save must never discard the editor.
      return true;
    }
  }
  function openWindow(role, path, host) {
    host = host || window;
    if (!(role in WINDOW_NAMES)) throw new Error("未知窗口类型");
    if (role === "display" ? path !== "/" : !["/settings", "/workflows", "/display-pages"].includes(path)) {
      throw new Error("管理路径未登记");
    }
    const target = host.open("", WINDOW_NAMES[role]);
    if (!target) throw new Error("浏览器阻止打开窗口，请允许本网站弹出窗口后重试");
    try {
      // An existing editor may contain unsaved changes. Focus it without navigation.
      if (target.location.href === "about:blank") target.location.replace(path);
      target.focus();
    } catch (_error) {
      throw new Error("无法访问原窗口，请关闭原窗口后重试");
    }
    return target;
  }
  return { WINDOW_NAMES, GESTURE_LABELS, lockPrompt, controllerView, fingerprint, DraftState, openWindow };
});
