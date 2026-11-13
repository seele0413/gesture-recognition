from __future__ import annotations

import math
import re
from typing import Any, Mapping

from app.control import GESTURES
from app.workflow import WORKFLOW_SCHEMA_VERSION


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_TOP_LEVEL = {
    "schema_version", "id", "name", "description", "enabled", "trigger",
    "nodes", "edges", "version", "created_at", "updated_at",
}
_REQUIRED_TOP_LEVEL = set(_TOP_LEVEL)
_NODE_TYPES = {"action", "condition", "delay", "wait_event", "end"}
_CONDITION_FIELDS = {"gesture", "confidence", "handedness", "target_id", "action"}
_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in"}


def validate_workflow(definition: Any, action_schemas: Mapping[str, dict]) -> list[str]:
    errors: list[str] = []
    if not isinstance(definition, dict):
        return ["工作流必须是 JSON 对象"]
    extra = set(definition) - _TOP_LEVEL
    if extra:
        errors.append("存在不支持的工作流字段：" + ", ".join(sorted(extra)))
    missing = _REQUIRED_TOP_LEVEL - set(definition)
    if missing:
        errors.append("缺少工作流字段：" + ", ".join(sorted(missing)))
    if isinstance(definition.get("schema_version"), bool) or definition.get("schema_version") != WORKFLOW_SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {WORKFLOW_SCHEMA_VERSION}")
    if not isinstance(definition.get("id"), str) or not _ID.fullmatch(definition["id"]):
        errors.append("工作流 id 格式无效")
    if not isinstance(definition.get("name"), str) or not 1 <= len(definition["name"].strip()) <= 80:
        errors.append("工作流名称长度必须为 1～80 个字符")
    if not isinstance(definition.get("description", ""), str) or len(definition.get("description", "")) > 500:
        errors.append("工作流描述不能超过 500 个字符")
    if not isinstance(definition.get("enabled"), bool):
        errors.append("enabled 必须为布尔值")
    if not isinstance(definition.get("version"), int) or isinstance(definition.get("version"), bool) or definition.get("version", 0) < 1:
        errors.append("version 必须为正整数")
    for timestamp_field in ("created_at", "updated_at"):
        if not isinstance(definition.get(timestamp_field), str) or not definition.get(timestamp_field):
            errors.append(f"{timestamp_field} 必须是非空字符串")
    trigger = definition.get("trigger")
    if not isinstance(trigger, dict):
        errors.append("trigger 必须是对象")
    else:
        trigger_type = trigger.get("type")
        if trigger_type == "gesture_trigger":
            if trigger.get("gesture") not in GESTURES:
                errors.append("手势触发器必须指定内置手势")
            if set(trigger) - {"type", "gesture"}:
                errors.append("手势触发器包含不支持的字段")
        elif trigger_type == "gesture_sequence_trigger":
            gestures = trigger.get("gestures")
            if not isinstance(gestures, list) or not 2 <= len(gestures) <= 5 or any(g not in GESTURES for g in gestures):
                errors.append("手势序列必须包含 2～5 个内置手势")
            window = trigger.get("sequence_window_ms", 5000)
            if not isinstance(window, int) or isinstance(window, bool) or not 1000 <= window <= 30000:
                errors.append("sequence_window_ms 必须为 1000～30000")
            if set(trigger) - {"type", "gestures", "sequence_window_ms"}:
                errors.append("手势序列触发器包含不支持的字段")
        elif trigger_type == "controller_locked":
            if set(trigger) != {"type"}:
                errors.append("controller_locked 触发器不接受额外参数")
        else:
            errors.append("无效的工作流触发器")

    nodes = definition.get("nodes")
    edges = definition.get("edges")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 100:
        errors.append("nodes 必须包含 1～100 个节点")
        nodes = []
    if not isinstance(edges, list) or len(edges) > 200:
        errors.append("edges 必须是最多 200 条的数组")
        edges = []

    node_map: dict[str, dict] = {}
    for index, node in enumerate(nodes):
        prefix = f"节点[{index}]"
        if not isinstance(node, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not _ID.fullmatch(node_id):
            errors.append(f"{prefix} id 格式无效")
            continue
        if node_id in node_map:
            errors.append(f"节点 ID 重复：{node_id}")
            continue
        node_map[node_id] = node
        node_type = node.get("type")
        if not isinstance(node_type, str) or node_type not in _NODE_TYPES:
            errors.append(f"{prefix} 类型无效")
            continue
        allowed = {"id", "type", "params", "position"}
        if node_type == "action":
            allowed.update({"action", "timeout_ms", "on_error", "retries"})
            action = node.get("action")
            schema = action_schemas.get(action) if isinstance(action, str) else None
            if schema is None:
                errors.append(f"{prefix} 动作未注册：{action}")
            else:
                errors.extend(_validate_params(node.get("params", {}), schema, f"{prefix} 参数"))
                retries = node.get("retries", 0)
                if not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= 2:
                    errors.append(f"{prefix} retries 必须为 0～2")
                elif retries and not schema.get("idempotent", False):
                    errors.append(f"{prefix} 动作不是幂等操作，不能自动重试")
            timeout = node.get("timeout_ms", 5000)
            if not isinstance(timeout, int) or isinstance(timeout, bool) or not 100 <= timeout <= 60000:
                errors.append(f"{prefix} timeout_ms 必须为 100～60000")
            if not isinstance(node.get("on_error", "stop"), str) or node.get("on_error", "stop") not in {"stop", "continue", "branch"}:
                errors.append(f"{prefix} on_error 必须是 stop、continue 或 branch")
        elif node_type in {"condition"}:
            allowed.add("params")
            errors.extend(_validate_condition(node.get("params", {}), prefix))
        elif node_type == "delay":
            allowed.add("params")
            params = node.get("params", {})
            if not isinstance(params, dict) or set(params) != {"delay_ms"} or not isinstance(params.get("delay_ms"), int) or isinstance(params.get("delay_ms"), bool) or not 0 <= params["delay_ms"] <= 30000:
                errors.append(f"{prefix} delay_ms 必须为 0～30000")
        elif node_type == "wait_event":
            allowed.update({"params", "timeout_ms"})
            params = node.get("params", {})
            if not isinstance(params, dict) or not isinstance(params.get("event"), str) or params.get("event") not in {"controller_locked", "controller_lost", "gesture"}:
                errors.append(f"{prefix} wait_event 类型无效")
            elif params.get("event") == "gesture" and params.get("gesture") not in GESTURES:
                errors.append(f"{prefix} gesture 等待条件无效")
            elif set(params) - ({"event", "gesture"} if params.get("event") == "gesture" else {"event"}):
                errors.append(f"{prefix} wait_event 含不支持的参数")
            timeout = node.get("timeout_ms", 10000)
            if not isinstance(timeout, int) or isinstance(timeout, bool) or not 100 <= timeout <= 60000:
                errors.append(f"{prefix} timeout_ms 必须为 100～60000")
        elif node_type == "end":
            allowed.add("params")
        extra_node = set(node) - allowed
        if extra_node:
            errors.append(f"{prefix} 含不支持的字段：" + ", ".join(sorted(extra_node)))
        if not isinstance(node.get("params", {}), dict):
            errors.append(f"{prefix} params 必须是对象")
        if node_type == "end" and node.get("params", {}) != {}:
            errors.append(f"{prefix} end params 必须为空对象")
        position = node.get("position")
        if position is not None and (
            not isinstance(position, dict)
            or set(position) != {"x", "y"}
            or any(not isinstance(position.get(axis), (int, float)) or isinstance(position.get(axis), bool) or not math.isfinite(position[axis]) or not 0 <= position[axis] <= 5000 for axis in ("x", "y"))
        ):
            errors.append(f"{prefix} position 必须包含 0～5000 范围内的 x、y")

    adjacency: dict[str, list[tuple[str, str | None]]] = {node_id: [] for node_id in node_map}
    incoming = {node_id: 0 for node_id in node_map}
    edge_keys: set[tuple[str, str, str | None]] = set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict) or set(edge) - {"source", "target", "when"}:
            errors.append(f"边[{index}] 结构无效")
            continue
        source, target, when = edge.get("source"), edge.get("target"), edge.get("when")
        if not isinstance(source, str) or not isinstance(target, str) or source not in node_map or target not in node_map:
            errors.append(f"边[{index}] 引用了不存在的节点")
            continue
        if when is not None and (not isinstance(when, str) or when not in {"true", "false", "error"}):
            errors.append(f"边[{index}] when 无效")
            continue
        key = (source, target, when)
        if key in edge_keys:
            errors.append(f"边[{index}] 重复")
            continue
        edge_keys.add(key)
        adjacency[source].append((target, when))
        incoming[target] += 1

    if node_map:
        roots = [node_id for node_id, count in incoming.items() if count == 0]
        if len(roots) != 1:
            errors.append("工作流必须且只能有一个起点")
        for node_id, node in node_map.items():
            outgoing = adjacency[node_id]
            node_type = node.get("type")
            if node_type == "action" and node.get("action") == "web.navigate_route":
                normal = [edge for edge in outgoing if edge[1] is None]
                if len(normal) != 1 or node_map.get(normal[0][0], {}).get("type") != "end":
                    errors.append(f"页面导航节点 {node_id} 必须是工作流最后一个动作")
            if node_type == "end" and outgoing:
                errors.append(f"结束节点 {node_id} 不能有后继边")
            elif node_type == "condition":
                if len(outgoing) != 2 or {when for _, when in outgoing} != {"false", "true"}:
                    errors.append(f"条件节点 {node_id} 必须各有一条 true/false 分支")
            elif node_type == "action" and node.get("on_error", "stop") == "branch":
                if len(outgoing) != 2 or sum(when == "error" for _, when in outgoing) != 1 or sum(when is None for _, when in outgoing) != 1:
                    errors.append(f"动作节点 {node_id} 的 branch 错误处理需要一条正常边和一条 error 边")
            elif node_type != "end" and len(outgoing) != 1:
                errors.append(f"节点 {node_id} 必须且只能有一条后继边")
            elif node_type not in {"end", "condition"} and outgoing and outgoing[0][1] is not None:
                errors.append(f"节点 {node_id} 的普通后继边不能带 when")

        color: dict[str, int] = {node_id: 0 for node_id in node_map}
        cycle = False

        def visit(node_id: str) -> None:
            nonlocal cycle
            color[node_id] = 1
            for target, _ in adjacency[node_id]:
                if color[target] == 1:
                    cycle = True
                elif color[target] == 0:
                    visit(target)
            color[node_id] = 2

        for node_id in node_map:
            if color[node_id] == 0:
                visit(node_id)
        if cycle:
            errors.append("工作流不允许存在循环")
        if len(roots) == 1:
            reachable: set[str] = set()
            stack = [roots[0]]
            while stack:
                current = stack.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                stack.extend(target for target, _ in adjacency[current])
            unreachable = set(node_map) - reachable
            if unreachable:
                errors.append("存在无法到达的节点：" + ", ".join(sorted(unreachable)))
            if not any(node.get("type") == "end" and node_id in reachable for node_id, node in node_map.items()):
                errors.append("工作流必须包含可到达的结束节点")

    return errors


def _validate_params(params: Any, schema: dict, prefix: str) -> list[str]:
    if not isinstance(params, dict):
        return [f"{prefix}必须是对象"]
    properties = schema.get("properties", {})
    errors: list[str] = []
    unknown = set(params) - set(properties)
    if unknown:
        errors.append(f"{prefix}存在未注册字段：" + ", ".join(sorted(unknown)))
    for name in schema.get("required", []):
        if name not in params:
            errors.append(f"{prefix}缺少 {name}")
    for name, value in params.items():
        rule = properties.get(name)
        if rule is None:
            continue
        kind = rule.get("type")
        valid_type = {
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
            "boolean": lambda v: isinstance(v, bool),
        }.get(kind, lambda _v: False)
        if not valid_type(value):
            errors.append(f"{prefix}.{name} 类型必须为 {kind}")
            continue
        if "enum" in rule and value not in rule["enum"]:
            errors.append(f"{prefix}.{name} 不是允许的选项")
        if kind == "string" and len(value) > rule.get("maxLength", 1000):
            errors.append(f"{prefix}.{name} 长度超限")
        if kind in {"integer", "number"}:
            if "minimum" in rule and value < rule["minimum"] or "maximum" in rule and value > rule["maximum"]:
                errors.append(f"{prefix}.{name} 超出允许范围")
    return errors


def _validate_condition(params: Any, prefix: str) -> list[str]:
    if not isinstance(params, dict) or set(params) != {"field", "operator", "value"}:
        return [f"{prefix} params 必须包含 field、operator、value"]
    field, operator = params["field"], params["operator"]
    if not isinstance(field, str) or field not in _CONDITION_FIELDS:
        return [f"{prefix} field 不允许读取该上下文"]
    if not isinstance(operator, str) or operator not in _OPERATORS:
        return [f"{prefix} operator 无效"]
    value = params["value"]
    if not isinstance(value, (str, int, float, bool, list)) or isinstance(value, float) and not math.isfinite(value):
        return [f"{prefix} value 类型无效"]
    if isinstance(value, (str, list)) and len(value) > 100:
        return [f"{prefix} value 长度超限"]
    if field == "gesture" and (not isinstance(value, str) or value not in GESTURES):
        return [f"{prefix} gesture value 无效"]
    if field == "handedness" and (not isinstance(value, str) or value not in {"Left", "Right"}):
        return [f"{prefix} handedness value 无效"]
    if field == "confidence" and (not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1):
        return [f"{prefix} confidence value 必须为 0～1"]
    if field in {"target_id", "action"} and not isinstance(value, str):
        return [f"{prefix} value 必须为字符串"]
    if field == "action" and value not in {"none", "play_pause", "volume_up", "volume_down", "mute_toggle"}:
        return [f"{prefix} action value 无效"]
    if operator in {"gt", "gte", "lt", "lte"} and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return [f"{prefix} 数值比较必须使用数字 value"]
    if operator == "in" and not isinstance(value, list):
        return [f"{prefix} in 比较必须使用数组 value"]
    return []
