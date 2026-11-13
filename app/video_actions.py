from __future__ import annotations

from app.action_engine import ActionRegistry
from app.database import ControlStore
from app.web_actions import BrowserCommandAdapter


def register_video_actions(registry: ActionRegistry, store: ControlStore, adapter: BrowserCommandAdapter) -> None:
    media_ids = [asset["id"] for asset in store.get_media_assets()]
    no_params = {}
    registrations = [
        ("video.load", {"media_id": {"type": "string", "title": "视频素材", "enum": media_ids}}, ["media_id"], True),
        ("video.play", no_params, [], True),
        ("video.pause", no_params, [], True),
        ("video.seek", {"position_ms": {"type": "integer", "title": "位置（毫秒）", "minimum": 0, "maximum": 86400000}}, ["position_ms"], True),
        ("video.set_volume", {"volume": {"type": "number", "title": "音量", "minimum": 0, "maximum": 1}}, ["volume"], True),
        ("video.mute", no_params, [], True),
        ("video.unmute", no_params, [], True),
        ("video.set_loop", {"enabled": {"type": "boolean", "title": "循环播放"}}, ["enabled"], True),
    ]
    for name, properties, required, idempotent in registrations:
        async def run(params, context, action=name):
            if action == "video.load":
                asset_id = params["media_id"]
                asset = store.get_media_asset(asset_id)
                if not asset or not asset["path"].is_file():
                    raise FileNotFoundError("登记的视频素材不存在")
                command_params = {**params, "url": f"/media/assets/{asset_id}"}
            else:
                command_params = params
            return await adapter.execute(action, command_params, context)
        registry.register(name, properties=properties, required=required, handler=run, idempotent=idempotent)
