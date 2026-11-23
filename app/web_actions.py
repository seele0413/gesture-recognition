from __future__ import annotations

from typing import Any, Callable

from app.action_engine import ActionRegistry
from app.display import DisplayCommandChannel
from app.display_pages import DISPLAY_PAGE_IDS


SCENES = ("welcome", "company_intro", "product_intro", "factory_intro", "presentation_mode")
PANELS = ("welcome", "company", "product", "factory", "presentation")
TEXT_FIELDS = ("headline", "subhead", "notice")
ROUTES = ("home", "settings", "workflows")


class BrowserCommandAdapter:
    def __init__(self, channel: DisplayCommandChannel) -> None:
        self.channel = channel

    async def execute(self, action: str, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return await self.channel.execute(
            {"run_id": context["run_id"], "command_id": context["command_id"], "action": action, "params": params},
            int(context["timeout_ms"]),
        )


def register_web_actions(
    registry: ActionRegistry,
    adapter: BrowserCommandAdapter,
    page_ids_provider: Callable[[], tuple[str, ...]] | None = None,
    page_labels_provider: Callable[[], dict[str, str]] | None = None,
) -> None:
    no_params = {}
    get_page_ids = page_ids_provider or (lambda: DISPLAY_PAGE_IDS)
    get_page_labels = page_labels_provider or (lambda: {})

    def browser(action: str):
        async def run(params: dict[str, Any], context: dict[str, Any]):
            if action == "web.navigate_page" and params.get("page_id") not in set(get_page_ids()):
                raise ValueError("目标展示页面不存在或已停用")
            return await adapter.execute(action, params, context)
        return run

    def enum_field(values: tuple[str, ...], title: str) -> dict:
        return {"type": "string", "title": title, "enum": list(values)}

    registrations = [
        ("web.navigate_route", {"route": enum_field(ROUTES, "允许的页面")}, ["route"], True),
        ("web.navigate_page", {"page_id": enum_field(DISPLAY_PAGE_IDS, "登记的展示主页")}, ["page_id"], True),
        ("web.navigate_parent", no_params, [], True),
        ("web.set_scene", {"scene": enum_field(SCENES, "展厅场景")}, ["scene"], True),
        ("web.show_panel", {"panel": enum_field(PANELS, "面板")}, ["panel"], True),
        ("web.hide_panel", {"panel": enum_field(PANELS, "面板")}, ["panel"], True),
        ("web.set_text", {
            "field": enum_field(TEXT_FIELDS, "文本字段"),
            "text": {"type": "string", "title": "显示文本", "maxLength": 160},
        }, ["field", "text"], True),
        ("web.return_home", no_params, [], True),
    ]
    for name, properties, required, idempotent in registrations:
        properties_provider = None
        if name == "web.navigate_page":
            properties_provider = lambda: {
                "page_id": {
                    **enum_field(tuple(get_page_ids()), "登记的展示页面"),
                    "enum_labels": get_page_labels(),
                }
            }
        registry.register(
            name,
            properties=properties,
            required=required,
            handler=browser(name),
            idempotent=idempotent,
            properties_provider=properties_provider,
        )
