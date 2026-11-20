import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.workflow import new_workflow
from app.workflow_generator import (
    DocumentParseError,
    ModelNotConfiguredError,
    ModelRequestError,
    WorkflowGenerationError,
    WorkflowGenerator,
    build_generated_workflow,
    build_plan_schema,
    compile_workflow_plan,
    external_page_control_issues,
    extract_document_text,
)


def make_docx(paragraphs=None):
    paragraphs = paragraphs or ["访客进入展厅", "播放企业宣传片"]
    body = "".join(
        f"<w:p><w:r><w:t>{value}</w:t></w:r></w:p>"
        for value in paragraphs
    )
    body += (
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>动作</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>切换页面</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    ).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def sample_plan():
    return {
        "name": "访客展厅讲解",
        "description": "按顺序播放宣传片",
        "summary": "先播放企业宣传片，然后结束。",
        "trigger": {"type": "gesture_trigger", "gesture": "Open_Palm"},
        "nodes": [
            {
                "id": "play-video",
                "type": "action",
                "action": "video.play",
                "params": {},
                "timeout_ms": 3000,
                "on_error": "stop",
                "retries": 0,
            },
            {"id": "finish", "type": "end", "params": {}},
        ],
        "edges": [{"source": "play-video", "target": "finish", "when": None}],
        "warnings": [],
        "questions": [],
    }


class DocumentExtractionTests(unittest.TestCase):
    def test_extracts_utf8_text_and_normalizes_whitespace(self):
        result = extract_document_text("需求.md", "\ufeff# 展厅流程\r\n\r\n播放宣传片  \r\n".encode("utf-8"))
        self.assertEqual(result["filename"], "需求.md")
        self.assertEqual(result["extension"], ".md")
        self.assertIn("# 展厅流程", result["text"])
        self.assertIn("播放宣传片", result["text"])
        self.assertNotIn("\r", result["text"])

    def test_extracts_docx_paragraphs_and_table_cells(self):
        result = extract_document_text("展厅流程.docx", make_docx())
        self.assertIn("访客进入展厅", result["text"])
        self.assertIn("播放企业宣传片", result["text"])
        self.assertIn("动作 | 切换页面", result["text"])

    def test_rejects_unsupported_extension_and_empty_files(self):
        with self.assertRaises(DocumentParseError):
            extract_document_text("workflow.exe", b"anything")
        with self.assertRaises(DocumentParseError):
            extract_document_text("empty.txt", b"")

    def test_rejects_oversized_upload(self):
        with self.assertRaises(DocumentParseError):
            extract_document_text("large.txt", b"x" * (5 * 1024 * 1024 + 1))

    def test_rejects_docx_with_entity_declarations(self):
        buffer = io.BytesIO()
        malicious_xml = (
            b'<!DOCTYPE x [<!ENTITY a "expanded">]>'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b"<w:body><w:p><w:r><w:t>&a;</w:t></w:r></w:p></w:body></w:document>"
        )
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", malicious_xml)
        with self.assertRaises(DocumentParseError):
            extract_document_text("malicious.docx", buffer.getvalue())


class WorkflowPlanCompilerTests(unittest.TestCase):
    def setUp(self):
        self.actions = {
            "video.play": {
                "properties": {},
                "required": [],
                "idempotent": True,
            }
        }

    def test_compiles_a_plan_to_existing_workflow_schema(self):
        workflow, warnings, questions, summary = build_generated_workflow(sample_plan(), self.actions)
        self.assertEqual(workflow["schema_version"], 1)
        self.assertFalse(workflow["enabled"])
        self.assertEqual([node["type"] for node in workflow["nodes"]], ["action", "end"])
        self.assertEqual(workflow["edges"], [{"source": "ai_001", "target": "ai_002"}])
        self.assertEqual(warnings, [])
        self.assertEqual(questions, [])
        self.assertIn("播放企业宣传片", summary)
        self.assertTrue(all("position" in node for node in workflow["nodes"]))

    def test_fills_missing_condition_branches_with_safe_end_paths(self):
        plan = sample_plan()
        plan["nodes"] = [
            {"id": "check", "type": "condition", "params": {"field": "confidence", "operator": "gte", "value": 0.7}},
            {"id": "finish", "type": "end", "params": {}},
        ]
        plan["edges"] = [{"source": "check", "target": "finish", "when": "true"}]
        workflow, warnings, _, _ = compile_workflow_plan(plan)
        self.assertEqual(
            {edge.get("when") for edge in workflow["edges"] if edge["source"] == "ai_001"},
            {"true", "false"},
        )
        self.assertTrue(any("false 分支未明确" in warning for warning in warnings))

    def test_cycle_does_not_hang_layout_and_is_left_for_validator_to_reject(self):
        plan = sample_plan()
        plan["nodes"] = [
            {"id": "one", "type": "action", "action": "video.play", "params": {}},
            {"id": "two", "type": "action", "action": "video.play", "params": {}},
            {"id": "finish", "type": "end", "params": {}},
        ]
        plan["edges"] = [
            {"source": "one", "target": "two", "when": None},
            {"source": "two", "target": "one", "when": None},
        ]
        workflow, _, _, _ = compile_workflow_plan(plan)
        self.assertEqual(len(workflow["nodes"]), 3)
        self.assertTrue(all("position" in node for node in workflow["nodes"]))

    def test_rejects_duplicate_ids_and_missing_edge_targets(self):
        plan = sample_plan()
        plan["nodes"][1]["id"] = "play-video"
        with self.assertRaises(WorkflowGenerationError):
            compile_workflow_plan(plan)
        plan = sample_plan()
        plan["edges"][0]["target"] = "missing"
        with self.assertRaises(WorkflowGenerationError):
            compile_workflow_plan(plan)

    def test_plan_schema_requires_strict_object_shapes(self):
        schema = build_plan_schema(self.actions)

        def visit(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertIs(value.get("additionalProperties"), False)
                    self.assertEqual(set(value.get("required", [])), set(value.get("properties", {})))
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(schema)

    def test_external_page_transition_rejects_local_dom_controls(self):
        pages = [
            {"page_id": "promo", "page_type": "local", "enabled": True},
            {"page_id": "company_website", "page_type": "external", "enabled": True},
        ]
        workflow = {
            "nodes": [
                {"id": "navigate", "type": "action", "action": "web.navigate_page", "params": {"page_id": "company_website"}},
                {"id": "scene", "type": "action", "action": "web.set_scene", "params": {"scene": "intro"}},
                {"id": "end", "type": "end", "params": {}},
            ],
            "edges": [
                {"source": "navigate", "target": "scene"},
                {"source": "scene", "target": "end"},
            ],
        }
        issues = external_page_control_issues(workflow, pages, "promo")
        self.assertTrue(any("外部网页之后" in issue for issue in issues))

    def test_external_navigation_can_return_to_local_home_before_local_controls(self):
        pages = [
            {"page_id": "promo", "page_type": "local", "enabled": True},
            {"page_id": "company_website", "page_type": "external", "enabled": True},
        ]
        workflow = {
            "nodes": [
                {"id": "navigate", "type": "action", "action": "web.navigate_page", "params": {"page_id": "company_website"}},
                {"id": "home", "type": "action", "action": "web.return_home", "params": {}},
                {"id": "scene", "type": "action", "action": "web.set_scene", "params": {"scene": "intro"}},
                {"id": "end", "type": "end", "params": {}},
            ],
            "edges": [
                {"source": "navigate", "target": "home"},
                {"source": "home", "target": "scene"},
                {"source": "scene", "target": "end"},
            ],
        }
        self.assertEqual(external_page_control_issues(workflow, pages, "promo"), [])

    def test_external_page_check_ignores_malformed_graph_fields_safely(self):
        malformed_workflows = [
            {"nodes": None, "edges": [None, {"source": [], "target": {}}]},
            {
                "nodes": [{"id": "scene", "type": "action", "action": "web.set_scene", "params": None}],
                "edges": None,
            },
            {"nodes": "not-a-node-list", "edges": {"source": "scene", "target": "scene"}},
        ]
        for workflow in malformed_workflows:
            with self.subTest(workflow=workflow):
                self.assertEqual(external_page_control_issues(workflow, [], "promo"), [])


class FakeResponse:
    def __init__(self, payload):
        self.data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self.data if size < 0 else self.data[:size]


class WorkflowGeneratorConfigurationTests(unittest.TestCase):
    def test_example_api_key_placeholder_is_not_treated_as_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("OPENAI_API_KEY=sk-your-api-key\n", encoding="utf-8")
            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
                generator = WorkflowGenerator(env_file=env_file)
                self.assertFalse(generator.status()["configured"])
                with self.assertRaises(ModelNotConfiguredError):
                    generator.generate_plan("播放宣传片", "", "Open_Palm", {}, [])

                env_file.write_text("OPENAI_API_KEY=sk-real-example-value\n", encoding="utf-8")
                self.assertTrue(generator.status()["configured"])


    def test_frontend_api_key_configuration_persists_and_preserves_other_env_values(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "# Existing model settings\nOPENAI_MODEL=gpt-4o-mini\n"
                "OPENAI_BASE_URL=https://api.example.test/v1\nOTHER_SETTING=keep-me\n"
                "OPENAI_API_KEY=old-key\n",
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
                generator = WorkflowGenerator(env_file=env_file)
                status = generator.configure_api_key("sk-new-local-key")
                saved = env_file.read_text(encoding="utf-8")
                self.assertTrue(status["configured"])
                self.assertNotIn("api_key", status)
                self.assertIn("OPENAI_API_KEY=sk-new-local-key", saved)
                self.assertIn("OPENAI_MODEL=gpt-4o-mini", saved)
                self.assertIn("OPENAI_BASE_URL=https://api.example.test/v1", saved)
                self.assertIn("OTHER_SETTING=keep-me", saved)
                self.assertEqual(saved.count("OPENAI_API_KEY="), 1)

    def test_frontend_api_key_configuration_rejects_whitespace_and_line_breaks(self):
        with tempfile.TemporaryDirectory() as directory:
            generator = WorkflowGenerator(env_file=Path(directory) / ".env")
            for invalid in ("", "sk-invalid key", "sk-invalid" + chr(10) + "OPENAI_MODEL=bad", "sk-your-api-key"):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    generator.configure_api_key(invalid)

    def test_full_model_configuration_is_saved_and_preserves_unrelated_env_values(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("OTHER_SETTING=keep-me\nOPENAI_API_KEY=old-key\n", encoding="utf-8")
            with patch.dict("os.environ", {
                "OPENAI_API_KEY": "", "OPENAI_MODEL": "", "OPENAI_BASE_URL": "", "OPENAI_API_PROTOCOL": "",
            }):
                generator = WorkflowGenerator(env_file=env_file)
                status = generator.configure(
                    api_key="relay-secret-key",
                    base_url="https://relay.example.test/v1",
                    model="deepseek-chat",
                    protocol="chat_completions",
                )
            saved = env_file.read_text(encoding="utf-8")
        self.assertTrue(status["configured"])
        self.assertEqual(status["provider"], "自定义中转站 / OpenAI 兼容服务")
        self.assertEqual(status["base_url"], "https://relay.example.test/v1")
        self.assertEqual(status["model"], "deepseek-chat")
        self.assertEqual(status["protocol"], "chat_completions")
        self.assertNotIn("api_key", status)
        self.assertNotIn("relay-secret-key", str(status))
        self.assertIn("OTHER_SETTING=keep-me", saved)
        self.assertIn("OPENAI_API_KEY=relay-secret-key", saved)
        self.assertIn("OPENAI_BASE_URL=https://relay.example.test/v1", saved)
        self.assertIn("OPENAI_MODEL=deepseek-chat", saved)
        self.assertIn("OPENAI_API_PROTOCOL=chat_completions", saved)

    def test_model_configuration_rejects_endpoint_paths_and_unknown_protocols(self):
        with tempfile.TemporaryDirectory() as directory:
            generator = WorkflowGenerator(env_file=Path(directory) / ".env")
            for invalid_url in ("ftp://relay.example.test/v1", "https://relay.example.test/v1/chat/completions"):
                with self.subTest(invalid_url=invalid_url), self.assertRaises(ValueError):
                    generator.configure(base_url=invalid_url)
            with self.assertRaises(ValueError):
                generator.configure(protocol="legacy")

    def test_chat_completions_protocol_sends_json_schema_and_parses_result(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "OPENAI_API_KEY=sk-test-key\nOPENAI_MODEL=deepseek-chat\n"
                "OPENAI_BASE_URL=https://relay.example.test/v1\nOPENAI_API_PROTOCOL=chat_completions\n",
                encoding="utf-8",
            )
            captured = {}

            def opener(request, timeout):
                captured["url"] = request.full_url
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                return FakeResponse({"choices": [{
                    "message": {"role": "assistant", "content": json.dumps(sample_plan(), ensure_ascii=False)},
                    "finish_reason": "stop",
                }]})

            with patch.dict("os.environ", {
                "OPENAI_API_KEY": "", "OPENAI_MODEL": "", "OPENAI_BASE_URL": "", "OPENAI_API_PROTOCOL": "",
            }):
                generator = WorkflowGenerator(env_file=env_file, opener=opener)
                plan = generator.generate_plan(
                    "播放企业宣传片", "", "Open_Palm",
                    {"video.play": {"properties": {}, "required": [], "idempotent": True}},
                    [],
                )
        self.assertEqual(plan["name"], "访客展厅讲解")
        self.assertEqual(captured["url"], "https://relay.example.test/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "deepseek-chat")
        self.assertEqual(captured["payload"]["response_format"]["type"], "json_schema")
        self.assertTrue(captured["payload"]["response_format"]["json_schema"]["strict"])

    def test_auto_protocol_falls_back_to_chat_completions_when_responses_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "OPENAI_API_KEY=sk-test-key\nOPENAI_MODEL=relay-model\n"
                "OPENAI_BASE_URL=https://relay.example.test/v1\nOPENAI_API_PROTOCOL=auto\n",
                encoding="utf-8",
            )
            calls = []

            def opener(request, timeout):
                calls.append(request.full_url)
                if request.full_url.endswith("/responses"):
                    body = json.dumps({"error": {"message": "Not Found"}}).encode("utf-8")
                    raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(body))
                return FakeResponse({"choices": [{
                    "message": {"role": "assistant", "content": json.dumps(sample_plan(), ensure_ascii=False)},
                    "finish_reason": "stop",
                }]})

            with patch.dict("os.environ", {
                "OPENAI_API_KEY": "", "OPENAI_MODEL": "", "OPENAI_BASE_URL": "", "OPENAI_API_PROTOCOL": "",
            }):
                generator = WorkflowGenerator(env_file=env_file, opener=opener)
                plan = generator.generate_plan(
                    "播放企业宣传片", "", "Open_Palm",
                    {"video.play": {"properties": {}, "required": [], "idempotent": True}},
                    [],
                )
        self.assertEqual(plan["name"], "访客展厅讲解")
        self.assertEqual(calls, [
            "https://relay.example.test/v1/responses",
            "https://relay.example.test/v1/chat/completions",
        ])

    def test_chat_completions_falls_back_to_json_mode_when_json_schema_is_unsupported(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "OPENAI_API_KEY=sk-test-key\nOPENAI_MODEL=relay-model\n"
                "OPENAI_BASE_URL=https://relay.example.test/v1\nOPENAI_API_PROTOCOL=chat_completions\n",
                encoding="utf-8",
            )
            formats = []

            def opener(request, timeout):
                payload = json.loads(request.data.decode("utf-8"))
                formats.append(payload["response_format"]["type"])
                if payload["response_format"]["type"] == "json_schema":
                    body = json.dumps({
                        "error": {"message": "response_format json_schema is not supported"}
                    }).encode("utf-8")
                    raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(body))
                return FakeResponse({"choices": [{
                    "message": {"role": "assistant", "content": json.dumps(sample_plan(), ensure_ascii=False)},
                    "finish_reason": "stop",
                }]})

            with patch.dict("os.environ", {
                "OPENAI_API_KEY": "", "OPENAI_MODEL": "", "OPENAI_BASE_URL": "", "OPENAI_API_PROTOCOL": "",
            }):
                generator = WorkflowGenerator(env_file=env_file, opener=opener)
                plan = generator.generate_plan(
                    "播放企业宣传片", "", "Open_Palm",
                    {"video.play": {"properties": {}, "required": [], "idempotent": True}},
                    [],
                )
        self.assertEqual(plan["name"], "访客展厅讲解")
        self.assertEqual(formats, ["json_schema", "json_object"])

    def test_connection_test_reports_actual_protocol_without_returning_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "OPENAI_API_KEY=relay-secret-key\nOPENAI_MODEL=relay-model\n"
                "OPENAI_BASE_URL=https://relay.example.test/v1\nOPENAI_API_PROTOCOL=chat_completions\n",
                encoding="utf-8",
            )

            def opener(request, timeout):
                return FakeResponse({"choices": [{
                    "message": {"role": "assistant", "content": "{\"ok\": true}"},
                    "finish_reason": "stop",
                }]})

            with patch.dict("os.environ", {
                "OPENAI_API_KEY": "", "OPENAI_MODEL": "", "OPENAI_BASE_URL": "", "OPENAI_API_PROTOCOL": "",
            }):
                result = WorkflowGenerator(env_file=env_file, opener=opener).test_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["protocol_used"], "chat_completions")
        self.assertEqual(result["model"], "relay-model")
        self.assertNotIn("api_key", result)
        self.assertNotIn("relay-secret-key", str(result))

    def test_http_error_never_echoes_the_full_api_key(self):
        secret = "sk-super-secret-test-value"
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                f"OPENAI_API_KEY={secret}\nOPENAI_MODEL=relay-model\n"
                "OPENAI_BASE_URL=https://relay.example.test/v1\nOPENAI_API_PROTOCOL=chat_completions\n",
                encoding="utf-8",
            )

            def opener(request, timeout):
                body = json.dumps({"error": {"message": "invalid key " + secret}}).encode("utf-8")
                raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(body))

            with patch.dict("os.environ", {
                "OPENAI_API_KEY": "", "OPENAI_MODEL": "", "OPENAI_BASE_URL": "", "OPENAI_API_PROTOCOL": "",
            }):
                generator = WorkflowGenerator(env_file=env_file, opener=opener)
                with self.assertRaises(ModelRequestError) as caught:
                    generator.test_connection()
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("[密钥已隐藏]", str(caught.exception))

    def test_responses_api_request_uses_strict_schema_and_parses_output(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "OPENAI_API_KEY=sk-test-key\nOPENAI_MODEL=gpt-4o-mini\n"
                "OPENAI_BASE_URL=https://api.example.test/v1\n",
                encoding="utf-8",
            )
            captured = {}

            def opener(request, timeout):
                captured["url"] = request.full_url
                captured["authorization"] = request.get_header("Authorization")
                captured["timeout"] = timeout
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                return FakeResponse({
                    "output": [{
                        "type": "message",
                        "content": [{
                            "type": "output_text",
                            "text": json.dumps(sample_plan(), ensure_ascii=False),
                        }],
                    }],
                })

            with patch.dict("os.environ", {
                "OPENAI_API_KEY": "",
                "OPENAI_MODEL": "",
                "OPENAI_BASE_URL": "",
            }):
                generator = WorkflowGenerator(env_file=env_file, opener=opener)
                plan = generator.generate_plan(
                    "播放企业宣传片",
                    "结束后停止",
                    "Open_Palm",
                    {"video.play": {"properties": {}, "required": [], "idempotent": True}},
                    [{"page_id": "promo", "title": "企业宣传片", "enabled": True}],
                )

        self.assertEqual(plan["name"], "访客展厅讲解")
        self.assertEqual(captured["url"], "https://api.example.test/v1/responses")
        self.assertEqual(captured["authorization"], "Bearer sk-test-key")
        self.assertEqual(captured["timeout"], 75)
        self.assertEqual(captured["payload"]["text"]["format"]["type"], "json_schema")
        self.assertTrue(captured["payload"]["text"]["format"]["strict"])
        self.assertEqual(captured["payload"]["model"], "gpt-4o-mini")


class WorkflowGeneratorClientTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.promo = root / "promo.mp4"
        self.promo.write_bytes(b"test-video")
        self.client = TestClient(create_app(root / "app.sqlite3", self.promo))

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def test_model_configuration_endpoint_saves_provider_settings_without_secret(self):
        expected_status = {
            "configured": True,
            "provider": "自定义中转站 / OpenAI 兼容服务",
            "model": "deepseek-chat",
            "base_url": "https://relay.example.test/v1",
            "protocol": "chat_completions",
            "protocol_label": "Chat Completions",
            "extensions": [".pdf", ".docx", ".txt", ".md"],
            "max_upload_bytes": 5 * 1024 * 1024,
            "max_extracted_chars": 32000,
        }
        with patch.object(WorkflowGenerator, "configure", return_value=expected_status) as configure:
            response = self.client.put(
                "/api/workflow-generator/config",
                json={
                    "api_key": "relay-test-key",
                    "base_url": "https://relay.example.test/v1",
                    "model": "deepseek-chat",
                    "protocol": "chat_completions",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["configured"])
        self.assertNotIn("api_key", response.json())
        self.assertNotIn("relay-test-key", response.text)
        configure.assert_called_once_with(
            api_key="relay-test-key",
            base_url="https://relay.example.test/v1",
            model="deepseek-chat",
            protocol="chat_completions",
        )

    def test_model_connection_test_endpoint_reports_provider_result(self):
        expected = {
            "ok": True,
            "provider": "自定义中转站 / OpenAI 兼容服务",
            "model": "deepseek-chat",
            "base_url": "https://relay.example.test/v1",
            "configured_protocol": "auto",
            "protocol_used": "chat_completions",
            "latency_ms": 123,
            "message": "模型连接成功，可以开始生成工作流",
        }
        with patch.object(WorkflowGenerator, "test_connection", return_value=expected):
            response = self.client.post("/api/workflow-generator/test")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["protocol_used"], "chat_completions")

    def test_generator_status_endpoint_is_available(self):
        response = self.client.get("/api/workflow-generator/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("configured", response.json())
        self.assertEqual(response.json()["provider"], "OpenAI 官方")
        self.assertEqual(response.json()["protocol"], "auto")
        self.assertEqual(response.json()["base_url"], "https://api.openai.com/v1")
        self.assertIn(".docx", response.json()["extensions"])

    def test_rejects_unsupported_file_before_calling_model(self):
        response = self.client.post(
            "/api/workflows/generate",
            files={"file": ("requirements.exe", b"not a document", "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("仅支持 PDF", response.json()["detail"])

    def test_generation_returns_unpersisted_draft_after_engine_validation(self):
        with patch.object(WorkflowGenerator, "generate_plan", return_value=sample_plan()):
            response = self.client.post(
                "/api/workflows/generate",
                files={"file": ("showroom.txt", "播放企业宣传片".encode("utf-8"), "text/plain")},
                data={"instructions": "先播放宣传片", "preferred_trigger": "Open_Palm"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["valid"], payload["validation_errors"])
        self.assertFalse(payload["workflow"]["enabled"])
        self.assertEqual(payload["source"]["filename"], "showroom.txt")
        self.assertEqual(self.client.get("/api/workflows").json()["workflows"], [])

    def test_missing_model_configuration_returns_actionable_error(self):
        with patch.object(WorkflowGenerator, "generate_plan", side_effect=ModelNotConfiguredError("请配置 API Key")):
            response = self.client.post(
                "/api/workflows/generate",
                files={"file": ("showroom.txt", b"showroom", "text/plain")},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("API Key", response.json()["detail"])

    def test_validation_api_rejects_local_page_controls_after_external_navigation(self):
        workflow = new_workflow("外部页面后执行本地动作")
        workflow["nodes"] = [
            {
                "id": "external",
                "type": "action",
                "action": "web.navigate_page",
                "params": {"page_id": "company_website"},
                "timeout_ms": 5000,
                "on_error": "stop",
                "retries": 0,
            },
            {
                "id": "local-scene",
                "type": "action",
                "action": "web.set_scene",
                "params": {"scene": "welcome"},
                "timeout_ms": 5000,
                "on_error": "stop",
                "retries": 0,
            },
            {"id": "end", "type": "end", "params": {}},
        ]
        workflow["edges"] = [
            {"source": "external", "target": "local-scene"},
            {"source": "local-scene", "target": "end"},
        ]
        response = self.client.post("/api/workflows/validate", json=workflow)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["valid"])
        self.assertTrue(any("外部网页之后" in item for item in response.json()["errors"]))


if __name__ == "__main__":
    unittest.main()
