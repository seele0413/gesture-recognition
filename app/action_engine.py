from __future__ import annotations

import asyncio
import inspect
import operator
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4

from app.database import ControlStore
from app.workflow import utc_now
from app.workflow_validator import validate_workflow


ActionHandler = Callable[[dict[str, Any], dict[str, Any]], Any | Awaitable[Any]]


class WorkflowTimeoutError(TimeoutError):
    pass


@dataclass(frozen=True)
class ActionSpec:
    name: str
    schema: dict[str, Any]
    idempotent: bool
    handler: ActionHandler


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, ActionSpec] = {}

    def register(
        self, name: str, *, properties: dict[str, dict], required: list[str],
        handler: ActionHandler, idempotent: bool,
    ) -> None:
        if name in self._actions:
            raise ValueError(f"动作已注册：{name}")
        self._actions[name] = ActionSpec(
            name=name,
            schema={
                "type": "object", "properties": properties, "required": list(required),
                "additionalProperties": False, "idempotent": bool(idempotent),
            },
            idempotent=bool(idempotent),
            handler=handler,
        )

    def schema_map(self) -> dict[str, dict[str, Any]]:
        return {name: spec.schema for name, spec in self._actions.items()}

    def describe(self) -> list[dict[str, Any]]:
        return [
            {"name": spec.name, "schema": spec.schema, "idempotent": spec.idempotent}
            for spec in sorted(self._actions.values(), key=lambda item: item.name)
        ]

    async def execute(self, name: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
        spec = self._actions.get(name)
        if not spec:
            raise ValueError(f"动作未注册：{name}")
        result = spec.handler(params, context)
        if inspect.isawaitable(result):
            return await result
        return result


class WorkflowEngine:
    """Runs validated workflows on the app loop, never on the vision thread."""

    def __init__(
        self,
        store: ControlStore,
        actions: ActionRegistry,
        publish: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.store = store
        self.actions = actions
        self.publish = publish or (lambda _event: None)
        self._active_task: asyncio.Task | None = None
        self._active_run_id: str | None = None
        self._active_workflow_id: str | None = None
        self._controller_track_id: str | None = None
        self._controller_state = "unlocked"
        self._display_connected = False
        self._cancel_reason = ""
        self._sequences: dict[str, list[tuple[str, int]]] = {}
        self._event_waiters: set[tuple[asyncio.Future, Callable[[dict[str, Any]], bool]]] = set()
        self._seen_events: set[tuple[str, str, int]] = set()
        self._closed = False

    def validate(self, definition: dict[str, Any]) -> list[str]:
        return validate_workflow(definition, self.actions.schema_map())

    @property
    def active_run_id(self) -> str | None:
        return self._active_run_id

    def set_display_connected(self, connected: bool) -> None:
        self._display_connected = bool(connected)
        if not self._display_connected:
            self.cancel_active("展示执行客户端断开，已取消后续动作")

    async def on_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """EventHub listener. Returns a modified gesture event when a workflow claims it."""
        event_type = event.get("type")
        if event_type == "controller":
            self._controller_state = str(event.get("state", "unlocked"))
            self._controller_track_id = event.get("track_id") if self._controller_state == "locked" else None
            self._notify_event_waiters(event)
            if self._controller_state != "locked":
                self.cancel_active("主控丢失或解除，已取消后续工作流动作")
            elif event.get("reason") in {"ok_gesture", "stream_reconnected"}:
                for definition in self.store.get_workflows(enabled_only=True):
                    if definition["trigger"].get("type") == "controller_locked":
                        self._start(definition, event)
            return None
        if event_type != "gesture":
            self._notify_event_waiters(event)
            return None

        self._notify_event_waiters(event)
        if not event.get("action_triggered"):
            return None
        target_id = str(event.get("target_id", ""))
        if self._controller_state != "locked" or target_id != self._controller_track_id:
            return None
        gesture = event.get("gesture")
        timestamp_ms = int(event.get("timestamp_ms", 0))
        event_key = (target_id, str(gesture), timestamp_ms)
        if event_key in self._seen_events:
            event["workflow_handled"] = True
            return event
        self._seen_events.add(event_key)
        if len(self._seen_events) > 512:
            self._seen_events = set(list(self._seen_events)[-256:])

        candidates: list[dict[str, Any]] = []
        claimed = False
        for definition in self.store.get_workflows(enabled_only=True):
            trigger = definition["trigger"]
            if trigger["type"] == "gesture_trigger" and trigger["gesture"] == gesture:
                candidates.append(definition)
                claimed = True
            elif trigger["type"] == "gesture_sequence_trigger":
                if self._advance_sequence(definition, str(gesture), timestamp_ms):
                    candidates.append(definition)
                    claimed = True

        if candidates:
            if len(candidates) == 1:
                self._start(candidates[0], event)
            else:
                self._emit({"type": "workflow", "status": "failed", "error": "同一手势匹配了多个工作流，请调整触发器"})
        if claimed:
            event["workflow_handled"] = True
            return event
        return None

    def _advance_sequence(self, definition: dict[str, Any], gesture: str, timestamp_ms: int) -> bool:
        workflow_id = definition["id"]
        trigger = definition["trigger"]
        sequence = trigger["gestures"]
        window_ms = trigger.get("sequence_window_ms", 5000)
        observations = self._sequences.get(workflow_id, [])
        observations = [(name, stamp) for name, stamp in observations if timestamp_ms - stamp <= window_ms]
        if observations and observations[-1][0] == gesture:
            observations = []
        expected_index = len(observations)
        if expected_index < len(sequence) and sequence[expected_index] == gesture:
            observations.append((gesture, timestamp_ms))
        elif sequence[0] == gesture:
            observations = [(gesture, timestamp_ms)]
        else:
            observations = []
        matched = len(observations) == len(sequence)
        self._sequences[workflow_id] = [] if matched else observations
        return matched

    def _start(self, definition: dict[str, Any], trigger_event: dict[str, Any]) -> str | None:
        if self._closed:
            return None
        if trigger_event.get("type") in {"gesture", "controller"} and not self._display_connected:
            self._emit({
                "type": "workflow", "workflow_id": definition["id"], "status": "failed",
                "error": "大屏展示页未连接，已暂停工作流触发",
            })
            return None
        if self._active_task and not self._active_task.done():
            self._emit({
                "type": "workflow", "workflow_id": definition["id"], "status": "failed",
                "error": "展示屏正执行另一个工作流，本次触发已拒绝",
            })
            return None
        errors = self.validate(definition)
        if errors:
            self._emit({"type": "workflow", "workflow_id": definition["id"], "status": "failed", "error": errors[0]})
            return None
        run_id = uuid4().hex
        created_at = utc_now()
        safe_trigger_event = {
            key: value for key, value in trigger_event.items()
            if key in {"type", "target_id", "gesture", "confidence", "handedness", "timestamp_ms", "action", "action_triggered", "state", "track_id", "reason"}
        }
        run = {
            "run_id": run_id, "workflow_id": definition["id"], "workflow_version": definition["version"],
            "status": "pending", "mode": "live", "trigger_event": safe_trigger_event,
            "created_at": created_at,
        }
        self.store.create_workflow_run(run)
        self._active_run_id = run_id
        self._active_workflow_id = definition["id"]
        self._cancel_reason = ""
        self._active_task = asyncio.create_task(self._run(definition, trigger_event, run_id), name=f"workflow-{run_id}")
        self._emit({"type": "workflow", "run_id": run_id, "workflow_id": definition["id"], "status": "pending"})
        return run_id

    async def dry_run(self, definition: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        errors = self.validate(definition)
        if errors:
            raise ValueError("；".join(errors))
        safe_context = {
            key: value for key, value in (context or {}).items()
            if key in {"gesture", "confidence", "handedness", "target_id", "action"}
            and isinstance(value, (str, int, float, bool))
        }
        run_id = uuid4().hex
        created_at = utc_now()
        self.store.create_workflow_run({
            "run_id": run_id, "workflow_id": definition["id"], "workflow_version": definition["version"],
            "status": "running", "mode": "dry_run", "created_at": created_at, "started_at": created_at,
        })
        try:
            results = await self._execute_graph(definition, safe_context, run_id, dry_run=True)
            finished_at = utc_now()
            self.store.update_workflow_run(run_id, status="success", result=results, finished_at=finished_at)
            return self.store.get_workflow_run(run_id) or {}
        except Exception as error:
            finished_at = utc_now()
            self.store.update_workflow_run(run_id, status="failed", error=str(error), finished_at=finished_at)
            return self.store.get_workflow_run(run_id) or {}

    def cancel_active(self, reason: str = "工作流已取消") -> bool:
        task = self._active_task
        if not task or task.done():
            return False
        self._cancel_reason = reason
        task.cancel()
        return True

    def cancel_workflow(self, workflow_id: str, reason: str = "工作流已删除") -> bool:
        if self._active_workflow_id != workflow_id:
            return False
        return self.cancel_active(reason)

    async def cancel_run(self, run_id: str) -> bool:
        if run_id != self._active_run_id:
            return False
        return self.cancel_active("用户取消工作流")

    async def close(self) -> None:
        self._closed = True
        self.cancel_active("服务关闭")
        task = self._active_task
        if task:
            await asyncio.gather(task, return_exceptions=True)
        for future, _predicate in tuple(self._event_waiters):
            if not future.done():
                future.cancel()
        self._event_waiters.clear()

    async def _run(self, definition: dict[str, Any], event: dict[str, Any], run_id: str) -> None:
        now = utc_now()
        self.store.update_workflow_run(run_id, status="running", started_at=now)
        self._emit({"type": "workflow", "run_id": run_id, "workflow_id": definition["id"], "status": "running"})
        context = {key: event.get(key) for key in ("gesture", "confidence", "handedness", "target_id", "action")}
        try:
            results = await self._execute_graph(definition, context, run_id, dry_run=False)
            self.store.update_workflow_run(run_id, status="success", result=results, finished_at=utc_now())
            self._emit({"type": "workflow", "run_id": run_id, "workflow_id": definition["id"], "status": "success"})
        except asyncio.CancelledError:
            self.store.update_workflow_run(
                run_id, status="cancelled", error=self._cancel_reason or "工作流已取消", finished_at=utc_now()
            )
            self._emit({"type": "workflow", "run_id": run_id, "workflow_id": definition["id"], "status": "cancelled", "error": self._cancel_reason})
        except WorkflowTimeoutError as error:
            self.store.update_workflow_run(run_id, status="timeout", error=str(error)[:500], finished_at=utc_now())
            self._emit({"type": "workflow", "run_id": run_id, "workflow_id": definition["id"], "status": "timeout", "error": str(error)[:300]})
        except Exception as error:
            self.store.update_workflow_run(run_id, status="failed", error=str(error)[:500], finished_at=utc_now())
            self._emit({"type": "workflow", "run_id": run_id, "workflow_id": definition["id"], "status": "failed", "error": str(error)[:300]})
        finally:
            if self._active_run_id == run_id:
                self._active_run_id = None
                self._active_workflow_id = None
                self._active_task = None

    async def _execute_graph(
        self, definition: dict[str, Any], context: dict[str, Any], run_id: str, *, dry_run: bool,
    ) -> list[dict[str, Any]]:
        nodes = {node["id"]: node for node in definition["nodes"]}
        outgoing: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in nodes}
        incoming = {node_id: 0 for node_id in nodes}
        for edge in definition["edges"]:
            outgoing[edge["source"]].append(edge)
            incoming[edge["target"]] += 1
        current = next(node_id for node_id, count in incoming.items() if count == 0)
        results: list[dict[str, Any]] = []
        for _ in range(len(nodes) + 1):
            node = nodes[current]
            node_type = node["type"]
            if node_type == "end":
                break
            if not dry_run and self._controller_state != "locked":
                raise asyncio.CancelledError
            started_at = utc_now()
            action_name = node.get("action") if node_type == "action" else node_type
            command_id = uuid4().hex if node_type == "action" and not dry_run else None
            step = {
                "node_id": current, "action": action_name, "command_id": command_id,
                "status": "running", "started_at": started_at,
            }
            self.store.save_workflow_step(run_id, step)
            self._emit({
                "type": "workflow_step", "run_id": run_id, "workflow_id": definition["id"],
                "node_id": current, "status": "running", "action": action_name,
            })
            error_text: str | None = None
            result: Any = None
            branch: str | None = None
            try:
                if node_type == "action":
                    if dry_run:
                        result = {"simulated": True, "action": action_name, "params": node.get("params", {})}
                    else:
                        attempts = node.get("retries", 0) + 1
                        failure: Exception | None = None
                        for attempt in range(attempts):
                            if attempt:
                                command_id = uuid4().hex
                                step["command_id"] = command_id
                            try:
                                operation = self.actions.execute(
                                    action_name, node.get("params", {}),
                                    {"run_id": run_id, "command_id": command_id, "timeout_ms": node.get("timeout_ms", 5000)},
                                )
                                result = await asyncio.wait_for(operation, timeout=node.get("timeout_ms", 5000) / 1000)
                                failure = None
                                break
                            except Exception as error:
                                failure = error
                        if failure is not None:
                            if isinstance(failure, TimeoutError):
                                raise WorkflowTimeoutError(str(failure) or f"动作 {action_name} 超时") from failure
                            raise failure
                elif node_type == "condition":
                    branch = "true" if _evaluate(node["params"], context) else "false"
                    result = {"condition": branch == "true", "field": node["params"]["field"]}
                elif node_type == "delay":
                    result = {"delay_ms": node["params"]["delay_ms"], "simulated": dry_run}
                    if not dry_run:
                        await asyncio.sleep(node["params"]["delay_ms"] / 1000)
                elif node_type == "wait_event":
                    if dry_run:
                        result = {"simulated": True, "event": node["params"]["event"]}
                    else:
                        result = await self._wait_for_event(node, node.get("timeout_ms", 10000))
                status = "simulated" if dry_run else "success"
            except asyncio.CancelledError:
                step.update(status="cancelled", error=self._cancel_reason or "工作流已取消", finished_at=utc_now())
                self.store.save_workflow_step(run_id, step)
                raise
            except Exception as error:
                status = "timeout" if isinstance(error, TimeoutError) else "failed"
                error_text = str(error)[:500]
                if node_type == "action" and node.get("on_error", "stop") == "branch":
                    branch = "error"
            step.update(status=status, result=result, error=error_text, finished_at=utc_now())
            self.store.save_workflow_step(run_id, step)
            results.append({"node_id": current, "status": status, "result": result, "error": error_text})
            self._emit({
                "type": "workflow_step", "run_id": run_id, "workflow_id": definition["id"],
                "node_id": current, "status": status, "action": action_name, "error": error_text,
            })
            if status in {"failed", "timeout"} and node.get("on_error", "stop") == "stop":
                if status == "timeout":
                    raise WorkflowTimeoutError(error_text or "工作流节点超时")
                raise RuntimeError(error_text or "工作流动作执行失败")
            if status in {"failed", "timeout"} and node.get("on_error", "stop") == "continue":
                branch = None
            edge = _select_edge(outgoing[current], branch)
            if edge is None:
                if status == "timeout":
                    raise WorkflowTimeoutError(error_text or "工作流节点超时")
                if status == "failed":
                    raise RuntimeError(error_text or "工作流动作执行失败")
                raise RuntimeError(f"节点 {current} 没有可执行的后继路径")
            current = edge["target"]
        else:
            raise RuntimeError("工作流超出最大节点步数")
        return results

    async def _wait_for_event(self, node: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
        params = node["params"]
        expected = params["event"]

        def matches(event: dict[str, Any]) -> bool:
            if expected == "controller_locked":
                return event.get("type") == "controller" and event.get("state") == "locked"
            if expected == "controller_lost":
                return event.get("type") == "controller" and event.get("state") in {"lost", "unlocked"}
            return event.get("type") == "gesture" and event.get("gesture") == params.get("gesture") and bool(event.get("action_triggered"))

        future = asyncio.get_running_loop().create_future()
        entry = (future, matches)
        self._event_waiters.add(entry)
        try:
            return await asyncio.wait_for(future, timeout_ms / 1000)
        finally:
            self._event_waiters.discard(entry)

    def _notify_event_waiters(self, event: dict[str, Any]) -> None:
        for future, predicate in tuple(self._event_waiters):
            if not future.done() and predicate(event):
                future.set_result(dict(event))

    def _emit(self, event: dict[str, Any]) -> None:
        try:
            self.publish(event)
        except Exception:
            pass


def _select_edge(edges: list[dict[str, Any]], branch: str | None) -> dict[str, Any] | None:
    desired = branch
    if desired is None:
        desired = next((edge.get("when") for edge in edges if edge.get("when") is None), None)
    return next((edge for edge in edges if edge.get("when") == desired), None)


def _evaluate(condition: dict[str, Any], context: dict[str, Any]) -> bool:
    left = context.get(condition["field"])
    right = condition["value"]
    op = condition["operator"]
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "in":
        return left in right
    compare = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le}[op]
    try:
        return bool(compare(left, right))
    except (TypeError, ValueError):
        return False
