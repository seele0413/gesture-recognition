from __future__ import annotations

from typing import Any

from app.action_engine import ActionRegistry
from app.display import DisplayCommandChannel


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


def register_web_actions(registry: ActionRegistry, adapter: BrowserCommandAdapter) -> None:
    no_params = {}

    def browser(action: str):
        async def run(params: dict[str, Any], context: dict[str, Any]):
            return await adapter.execute(action, params, context)
        return run

    def enum_field(values: tuple[str, ...], title: str) -> dict:
        return {"type": "string", "title": title, "enum": list(values)}

    registrations = [
        ("web.navigate_route", {"route": enum_field(ROUTES, "允许的页面")}, ["route"], True),
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
        registry.register(name, properties=properties, required=required, handler=browser(name), idempotent=idempotent)
