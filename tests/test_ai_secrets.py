"""Disposable, provider-free checks of AI credential response boundaries."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from catlabel.api import routes_ai
from catlabel.core.models import AIConfig, AIConversation, AIModelConfig, AIProvider
from catlabel.services.ai_secrets import (
    REDACTED,
    known_environment_secrets,
    redact_secrets,
    secret_values,
)

SAMPLE_KEY = "test-provider-placeholder-secret"
PRIVATE_BODY = "test-private-key-placeholder-body"
VERTEX_KEY = json.dumps(
    {
        "type": "service_account",
        "private_key": f"-----BEGIN PRIVATE KEY-----\n{PRIVATE_BODY}\n-----END PRIVATE KEY-----\n",
        "client_email": "example@example.invalid",
    }
)


class AISecretBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        cwd = os.getcwd()
        os.chdir(self.tempdir.name)
        self.addCleanup(os.chdir, cwd)
        from catlabel.core import database

        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        self.addCleanup(self.engine.dispose)
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(database, "engine", self.engine)
        self.engine_patch.start()
        self.addCleanup(self.engine_patch.stop)
        app = FastAPI()
        app.include_router(routes_ai.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        fake_main = ModuleType("catlabel.api.main")
        fake_main.__dict__["get_agent_context"] = lambda: {
            "engine_rules": {"hardware_width_mm": 48}
        }
        self.main_patch = patch.dict(sys.modules, {"catlabel.api.main": fake_main})
        self.main_patch.start()
        self.addCleanup(self.main_patch.stop)
        self.prompt_patch = patch(
            "catlabel.services.prompts.build_system_prompt",
            return_value="Test system prompt.",
        )
        self.prompt_patch.start()
        self.addCleanup(self.prompt_patch.stop)

    def seed(
        self, key: str = SAMPLE_KEY, provider_type: str = "openai"
    ) -> tuple[int, int]:
        with Session(self.engine) as session:
            provider = AIProvider(name="Test", provider=provider_type, api_key=key)
            session.add(provider)
            session.flush()
            assert provider.id is not None
            provider_id = provider.id
            model = AIModelConfig(
                provider_id=provider_id, model_name="test-model", is_active=True
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            assert model.id is not None
            return provider_id, model.id

    def payload(self, provider_id: int | None = None, **updates: Any) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": provider_id,
            "name": "Edited",
            "provider": "openai",
            "base_url": "",
            "use_env": False,
            "vertex_region": "",
            "models": [],
        }
        value.update(updates)
        return value

    def saved_key(self, provider_id: int) -> str:
        with Session(self.engine) as session:
            provider = session.get(AIProvider, provider_id)
            assert provider is not None
            return provider.api_key

    def chat(self) -> dict[str, Any]:
        result = self.client.post(
            "/api/ai/chat",
            json={
                "messages": [{"role": "user", "content": "test message"}],
                "canvas_state": {},
            },
        )
        self.assertEqual(result.status_code, 200)
        return result.json()

    def test_config_get_omits_secret_and_keeps_models_shape(self) -> None:
        provider_id, model_id = self.seed()
        result = self.client.get("/api/ai/config").json()
        self.assertNotIn(SAMPLE_KEY, json.dumps(result))
        self.assertNotIn("api_key", result[0])
        self.assertTrue(result[0]["has_api_key"])
        self.assertEqual(result[0]["id"], provider_id)
        self.assertEqual(result[0]["models"][0]["id"], model_id)
        self.assertEqual(
            set(result[0]["models"][0]),
            {
                "id",
                "provider_id",
                "name",
                "model_name",
                "vision_capable",
                "reasoning_effort",
                "is_active",
            },
        )

    def test_config_get_never_seeds_even_with_legacy_row(self) -> None:
        with Session(self.engine) as session:
            session.add(AIConfig(api_key=SAMPLE_KEY))
            session.commit()
        for _ in range(2):
            self.assertEqual(self.client.get("/api/ai/config").json(), [])
        with Session(self.engine) as session:
            self.assertEqual(list(session.exec(select(AIProvider))), [])
            self.assertEqual(list(session.exec(select(AIModelConfig))), [])
        with self.engine.connect() as connection:
            self.assertIsNone(
                connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE name='catlabel_migrations'"
                ).first()
            )

    def test_save_preserves_replaces_and_explicitly_clears(self) -> None:
        provider_id, _ = self.seed()
        for update in ({}, {"api_key": None}, {"api_key": ""}):
            self.assertEqual(
                self.client.post(
                    "/api/ai/config", json=self.payload(provider_id, **update)
                ).status_code,
                200,
            )
            self.assertEqual(self.saved_key(provider_id), SAMPLE_KEY)
        self.client.post(
            "/api/ai/config",
            json=self.payload(provider_id, api_key="replacement-placeholder"),
        )
        self.assertEqual(self.saved_key(provider_id), "replacement-placeholder")
        self.client.post(
            "/api/ai/config", json=self.payload(provider_id, clear_api_key=True)
        )
        self.assertEqual(self.saved_key(provider_id), "")
        self.assertFalse(self.client.get("/api/ai/config").json()[0]["has_api_key"])
        response = self.client.post("/api/ai/config", json=self.payload())
        self.assertEqual(self.saved_key(response.json()["id"]), "")

    def test_conflict_and_unknown_id_do_not_write_or_deactivate_models(self) -> None:
        provider_id, model_id = self.seed()
        active_models = [
            {
                "name": "new",
                "model_name": "new",
                "vision_capable": False,
                "reasoning_effort": "",
                "is_active": True,
            }
        ]
        for body, expected in (
            (
                self.payload(
                    provider_id,
                    api_key="replacement-placeholder",
                    clear_api_key=True,
                    models=active_models,
                ),
                400,
            ),
            (self.payload(99999, models=active_models), 404),
        ):
            self.assertEqual(
                self.client.post("/api/ai/config", json=body).status_code, expected
            )
            self.assertEqual(self.saved_key(provider_id), SAMPLE_KEY)
            with Session(self.engine) as session:
                model = session.get(AIModelConfig, model_id)
                assert model is not None
                self.assertTrue(model.is_active)
                self.assertEqual(len(list(session.exec(select(AIProvider)))), 1)
                self.assertEqual(len(list(session.exec(select(AIModelConfig)))), 1)

    def test_legacy_migration_copies_once_and_does_not_resurrect(self) -> None:
        with Session(self.engine) as session:
            session.add(
                AIConfig(
                    provider="custom",
                    model_name="custom/test",
                    api_key=SAMPLE_KEY,
                    base_url="https://example.invalid",
                    use_env=True,
                    vertex_region="test-region",
                )
            )
            session.commit()
        routes_ai.migrate_legacy_provider(self.engine)
        routes_ai.migrate_legacy_provider(self.engine)
        result = self.client.get("/api/ai/config").json()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["provider"], "custom")
        self.assertEqual(result[0]["models"][0]["model_name"], "custom/test")
        self.assertEqual(result[0]["base_url"], "https://example.invalid")
        self.assertEqual(result[0]["vertex_region"], "test-region")
        self.assertTrue(result[0]["use_env"])
        self.assertTrue(result[0]["models"][0]["vision_capable"])
        self.assertEqual(self.saved_key(result[0]["id"]), SAMPLE_KEY)
        self.client.delete(f"/api/ai/config/{result[0]['id']}")
        routes_ai.migrate_legacy_provider(self.engine)
        self.assertEqual(self.client.get("/api/ai/config").json(), [])
        with Session(self.engine) as session:
            old = session.get(AIConfig, 1)
            assert old is not None
            self.assertEqual(old.api_key, SAMPLE_KEY)
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.exec_driver_sql(
                    "SELECT name FROM catlabel_migrations"
                ).all(),
                [("ai_providers_v1",)],
            )

    def test_migration_marks_empty_or_existing_installations(self) -> None:
        for existing in (False, True):
            with self.subTest(existing=existing):
                other = create_engine("sqlite://", poolclass=StaticPool)
                self.addCleanup(other.dispose)
                SQLModel.metadata.create_all(other)
                with Session(other) as session:
                    if existing:
                        session.add(
                            AIProvider(name="Existing", api_key="existing-placeholder")
                        )
                        session.add(AIConfig(api_key=SAMPLE_KEY))
                        session.commit()
                routes_ai.migrate_legacy_provider(other)
                with Session(other) as session:
                    for provider in session.exec(select(AIProvider)).all():
                        session.delete(provider)
                    if not existing:
                        session.add(AIConfig(api_key=SAMPLE_KEY))
                    session.commit()
                routes_ai.migrate_legacy_provider(other)
                with Session(other) as session:
                    self.assertEqual(list(session.exec(select(AIProvider))), [])

    def test_migration_failure_rolls_back_provider_and_marker(self) -> None:
        with Session(self.engine) as session:
            session.add(AIConfig(api_key=SAMPLE_KEY))
            session.commit()
        original_flush = Session.flush
        calls = 0

        def fail_second_flush(session, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise RuntimeError("migration-placeholder-failure")
            return original_flush(session, *args, **kwargs)

        with (
            patch.object(Session, "flush", fail_second_flush),
            self.assertRaises(RuntimeError),
        ):
            routes_ai.migrate_legacy_provider(self.engine)
        with Session(self.engine) as session:
            self.assertEqual(list(session.exec(select(AIProvider))), [])
            self.assertEqual(list(session.exec(select(AIModelConfig))), [])
        routes_ai.migrate_legacy_provider(self.engine)
        self.assertEqual(len(self.client.get("/api/ai/config").json()), 1)

    def test_history_and_trace_readbacks_redact_old_persisted_secrets(self) -> None:
        self.seed()
        with Session(self.engine) as session:
            session.add(AIConfig(api_key="legacy-placeholder-secret"))
            conversation = AIConversation(
                updated_at=datetime.utcnow(),
                title=SAMPLE_KEY,
                messages_json=json.dumps(
                    [
                        {
                            "role": "user",
                            "content": f"{SAMPLE_KEY} legacy-placeholder-secret",
                        }
                    ]
                ),
            )
            session.add(conversation)
            session.flush()
            conv_id = conversation.id
            session.add(
                routes_ai.AITraceLog(
                    conversation_id=conv_id,
                    timestamp=datetime.now(UTC).replace(tzinfo=None),
                    request_messages_json=json.dumps(
                        [{"token": "arbitrary-token-placeholder"}]
                    ),
                    response_message_json=json.dumps(
                        {"content": SAMPLE_KEY, "private_key": PRIVATE_BODY}
                    ),
                )
            )
            session.commit()
        for path in (
            "/api/ai/history",
            f"/api/ai/history/{conv_id}",
            f"/api/ai/history/{conv_id}/trace",
        ):
            result = self.client.get(path)
            self.assertEqual(result.status_code, 200)
            for secret in (
                SAMPLE_KEY,
                "legacy-placeholder-secret",
                PRIVATE_BODY,
                "arbitrary-token-placeholder",
            ):
                self.assertNotIn(secret, result.text)

    def seed_observation(self) -> tuple[int, int, datetime, datetime]:
        with Session(self.engine) as session:
            conversation = AIConversation(
                title=f"title {SAMPLE_KEY}",
                messages_json=json.dumps(
                    [
                        {
                            "role": "user",
                            "content": f"old {SAMPLE_KEY}",
                            "token": "ordinary-canvas-field",
                        }
                    ]
                ),
                updated_at=datetime.utcnow(),
            )
            session.add(conversation)
            session.flush()
            assert conversation.id is not None
            trace = routes_ai.AITraceLog(
                conversation_id=conversation.id,
                model_used=f"model {SAMPLE_KEY}",
                request_messages_json=json.dumps([{"content": SAMPLE_KEY}]),
                response_message_json=json.dumps({"content": SAMPLE_KEY}),
            )
            session.add(trace)
            session.commit()
            session.refresh(conversation)
            session.refresh(trace)
            assert trace.id is not None
            return conversation.id, trace.id, conversation.updated_at, trace.timestamp

    def test_retired_keys_physically_scrub_old_history_and_traces(self) -> None:
        for mode in ("replace", "clear", "delete"):
            with self.subTest(mode=mode):
                provider_id, _ = self.seed()
                conv_id, trace_id, updated_at, timestamp = self.seed_observation()
                if mode == "delete":
                    result = self.client.delete(f"/api/ai/config/{provider_id}")
                else:
                    update = (
                        {"api_key": "new-placeholder"}
                        if mode == "replace"
                        else {"clear_api_key": True}
                    )
                    result = self.client.post(
                        "/api/ai/config", json=self.payload(provider_id, **update)
                    )
                self.assertEqual(result.status_code, 200)
                for path in (
                    f"/api/ai/history/{conv_id}",
                    f"/api/ai/history/{conv_id}/trace",
                ):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn(SAMPLE_KEY, response.text)
                    if not path.endswith("/trace"):
                        self.assertEqual(
                            response.json()["messages"][0]["token"],
                            "ordinary-canvas-field",
                        )
                with Session(self.engine) as session:
                    conversation = session.get(AIConversation, conv_id)
                    trace = session.get(routes_ai.AITraceLog, trace_id)
                    assert conversation is not None and trace is not None
                    self.assertEqual(conversation.updated_at, updated_at)
                    self.assertEqual(trace.timestamp, timestamp)
                    self.assertEqual(trace.conversation_id, conv_id)
                    self.assertEqual(
                        json.loads(conversation.messages_json)[0]["role"], "user"
                    )
                    self.assertEqual(
                        json.loads(conversation.messages_json)[0]["token"],
                        "ordinary-canvas-field",
                    )
                    self.assertEqual(
                        json.loads(trace.request_messages_json)[0]["content"], REDACTED
                    )
                    self.assertEqual(
                        json.loads(trace.response_message_json)["content"], REDACTED
                    )
                    self.assertNotIn(
                        SAMPLE_KEY,
                        conversation.title
                        + conversation.messages_json
                        + trace.model_used
                        + trace.request_messages_json
                        + trace.response_message_json,
                    )
                with self.engine.connect() as connection:
                    stored_conversation = connection.exec_driver_sql(
                        "SELECT title, messages_json FROM aiconversation WHERE id=?",
                        (conv_id,),
                    ).first()
                    stored_trace = connection.exec_driver_sql(
                        "SELECT model_used, request_messages_json, response_message_json FROM aitracelog WHERE id=?",
                        (trace_id,),
                    ).first()
                    self.assertNotIn(
                        SAMPLE_KEY, str(stored_conversation) + str(stored_trace)
                    )

    def test_credential_retirement_and_scrub_roll_back_together(self) -> None:
        provider_id, model_id = self.seed()
        conv_id, _, _, _ = self.seed_observation()

        def failing_scrub(session, secrets):
            conversation = session.get(AIConversation, conv_id)
            assert conversation is not None
            conversation.title = REDACTED
            session.add(conversation)
            session.flush()
            raise RuntimeError("scrub-placeholder-failure")

        for mode in ("replace", "clear", "delete"):
            with (
                self.subTest(mode=mode),
                patch.object(
                    routes_ai, "_redact_stored_observability", side_effect=failing_scrub
                ),
                self.assertRaisesRegex(RuntimeError, "scrub-placeholder-failure"),
            ):
                if mode == "delete":
                    routes_ai.delete_provider(provider_id)
                else:
                    update = (
                        {"api_key": "new-placeholder"}
                        if mode == "replace"
                        else {"clear_api_key": True}
                    )
                    routes_ai.save_provider(
                        routes_ai.ProviderDTO(**self.payload(provider_id, **update))
                    )
            self.assertEqual(self.saved_key(provider_id), SAMPLE_KEY)
            with Session(self.engine) as session:
                conversation = session.get(AIConversation, conv_id)
                model = session.get(AIModelConfig, model_id)
                assert conversation is not None and model is not None
                self.assertEqual(conversation.title, f"title {SAMPLE_KEY}")
                self.assertTrue(model.is_active)

    def test_environment_credentials_redacted_for_use_env_provider(self) -> None:
        provider_id, _ = self.seed(key="")
        with Session(self.engine) as session:
            provider = session.get(AIProvider, provider_id)
            assert provider is not None
            provider.use_env = True
            session.add(provider)
            session.commit()
        credential_path = Path(self.tempdir.name) / "placeholder-service-account.json"
        credential_path.write_text(VERTEX_KEY)
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": SAMPLE_KEY,
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credential_path),
                },
            ),
            patch.object(
                routes_ai.litellm,
                "completion",
                side_effect=RuntimeError(
                    f"error {SAMPLE_KEY} {PRIVATE_BODY} {credential_path}"
                ),
            ),
            self.assertLogs(routes_ai.logger, level="INFO") as logs,
        ):
            result = self.chat()
            known = known_environment_secrets()
            self.assertIn(SAMPLE_KEY, known)
            self.assertIn(PRIVATE_BODY, known)
            self.assertIn(str(credential_path), known)
        for secret in (SAMPLE_KEY, PRIVATE_BODY, str(credential_path)):
            self.assertNotIn(secret, json.dumps(result))
            self.assertNotIn(secret, "\n".join(logs.output))

    def test_provider_error_redacted_in_response_and_log(self) -> None:
        self.seed()
        with (
            patch.object(
                routes_ai.litellm,
                "completion",
                side_effect=RuntimeError(f"Bad token {SAMPLE_KEY}"),
            ),
            self.assertLogs(routes_ai.logger, level="INFO") as logs,
        ):
            result = self.chat()
        self.assertIn(REDACTED, result["error"])
        self.assertEqual(len(result["error_id"]), 32)
        self.assertNotIn(SAMPLE_KEY, json.dumps(result))
        self.assertNotIn(SAMPLE_KEY, "\n".join(logs.output))
        self.assertNotIn("Traceback", "\n".join(logs.output))

    def test_tool_logs_and_new_trace_writes_redact_and_keep_naive_storage(self) -> None:
        self.seed()
        arguments = json.dumps(
            {"text": SAMPLE_KEY, "nested": {"api_key": "argument-placeholder"}}
        )
        tool_call = {
            "id": "test-call",
            "function": {"name": "test_tool", "arguments": arguments},
        }
        tool_message = SimpleNamespace(
            model_dump=lambda **kwargs: {
                "role": "assistant",
                "content": SAMPLE_KEY,
                "tool_calls": [tool_call],
            },
            tool_calls=[tool_call],
        )
        final_message = SimpleNamespace(
            model_dump=lambda **kwargs: {"role": "assistant", "content": "done"},
            tool_calls=None,
        )
        responses = iter(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(message=tool_message)], model="test-model"
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(message=final_message)], model="test-model"
                ),
            ]
        )

        def complete(**kwargs):
            self.assertNotIn(SAMPLE_KEY, json.dumps(kwargs["messages"]))
            return next(responses)

        with (
            patch.object(routes_ai.litellm, "completion", side_effect=complete),
            patch.object(routes_ai.litellm, "completion_cost", return_value=0),
            patch.object(
                routes_ai, "execute_tool", return_value=f"result {SAMPLE_KEY}"
            ),
            self.assertLogs(routes_ai.logger, level="INFO") as logs,
        ):
            result = self.client.post(
                "/api/ai/chat",
                json={
                    "messages": [{"role": "user", "content": f"test {SAMPLE_KEY}"}],
                    "canvas_state": {},
                    "conv_id": 77,
                },
            )
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("error", result.json())
        self.assertNotIn(SAMPLE_KEY, result.text)
        self.assertNotIn(SAMPLE_KEY, "\n".join(logs.output))
        self.assertNotIn("argument-placeholder", "\n".join(logs.output))
        with Session(self.engine) as session:
            traces = session.exec(select(routes_ai.AITraceLog)).all()
            self.assertEqual(len(traces), 2)
            for trace in traces:
                self.assertIsNone(trace.timestamp.tzinfo)
                self.assertNotIn(
                    SAMPLE_KEY,
                    trace.request_messages_json + trace.response_message_json,
                )
                self.assertNotIn("argument-placeholder", trace.response_message_json)
        with self.engine.connect() as connection:
            raw = connection.exec_driver_sql(
                "SELECT timestamp, typeof(timestamp) FROM aitracelog"
            ).all()
            self.assertTrue(all(row[1] == "text" for row in raw))
            self.assertTrue(all("+00:00" not in row[0] for row in raw))

    def test_vertex_tempfile_cleanup_at_every_exit(self) -> None:
        self.seed(VERTEX_KEY, "vertex_ai")
        paths: list[Path] = []
        original = tempfile.NamedTemporaryFile

        def create_file(*args, **kwargs):
            result = original(*args, dir=self.tempdir.name, **kwargs)
            paths.append(Path(result.name))
            return result

        successful_message = SimpleNamespace(
            model_dump=lambda **kwargs: {"role": "assistant", "content": "done"},
            tool_calls=None,
        )
        successful_response = SimpleNamespace(
            choices=[SimpleNamespace(message=successful_message)], model="test-model"
        )
        for mode in ("provider_failure", "setup_failure", "success", "cancellation"):
            with (
                self.subTest(mode=mode),
                patch.object(
                    routes_ai.tempfile, "NamedTemporaryFile", side_effect=create_file
                ),
                patch.object(routes_ai.litellm, "completion_cost", return_value=0),
            ):

                def complete(_mode=mode, **kwargs):
                    path = Path(kwargs["vertex_credentials"])
                    self.assertTrue(path.exists())
                    self.assertEqual(path.read_text(), VERTEX_KEY)
                    self.assertNotIn(PRIVATE_BODY, json.dumps(kwargs["messages"]))
                    if _mode == "provider_failure":
                        raise RuntimeError(
                            f"Credential {VERTEX_KEY} private-key-piece {PRIVATE_BODY}"
                        )
                    if _mode == "cancellation":
                        raise asyncio.CancelledError()
                    return successful_response

                setup_error = (
                    RuntimeError(f"setup failed {PRIVATE_BODY}")
                    if mode == "setup_failure"
                    else None
                )
                with (
                    patch.object(routes_ai.litellm, "completion", side_effect=complete),
                    patch(
                        "catlabel.services.prompts.build_system_prompt",
                        side_effect=setup_error,
                        return_value="Test prompt.",
                    ),
                    self.assertLogs(routes_ai.logger, level="INFO") as logs,
                ):
                    if mode == "cancellation":
                        with self.assertRaises(asyncio.CancelledError):
                            routes_ai.chat_with_agent(
                                routes_ai.ChatRequest(
                                    messages=[
                                        {"role": "user", "content": "test message"}
                                    ],
                                    canvas_state={},
                                )
                            )
                    else:
                        result = self.chat()
                        self.assertNotIn(PRIVATE_BODY, json.dumps(result))
                        self.assertNotIn(VERTEX_KEY, json.dumps(result))
                self.assertNotIn(PRIVATE_BODY, "\n".join(logs.output))
                self.assertTrue(paths)
                self.assertFalse(paths[-1].exists())


class RedactionTests(unittest.TestCase):
    def test_functional_data_keeps_ordinary_fields_and_json_spacing(self) -> None:
        text = '{ "token" : "label value", "private_key" : "ordinary data" }'
        data = {"token": "label value", "text": text, "secret": SAMPLE_KEY}
        result = redact_secrets(data, [SAMPLE_KEY], redact_fields=False)
        self.assertEqual(result["token"], "label value")
        self.assertEqual(result["text"], text)
        self.assertEqual(result["secret"], REDACTED)

    def test_nested_encoded_json_and_normalized_fields(self) -> None:
        data = {
            "api-key": "one",
            "nested": [
                {
                    "Authorization": "two",
                    "access_token": "three",
                    "client_secret": "four",
                },
                json.dumps(
                    [
                        {"private_key": PRIVATE_BODY},
                        {"Token": "five", "text": SAMPLE_KEY},
                    ]
                ),
                f"known {SAMPLE_KEY}",
            ],
        }
        result = redact_secrets(data, secret_values([SAMPLE_KEY]))
        self.assertEqual(result["api-key"], REDACTED)
        parsed = json.loads(result["nested"][1])
        self.assertEqual(parsed[0]["private_key"], REDACTED)
        self.assertEqual(parsed[1]["text"], REDACTED)
        self.assertEqual(result["nested"][2], f"known {REDACTED}")
        self.assertNotIn(SAMPLE_KEY, json.dumps(result))
        self.assertNotIn(PRIVATE_BODY, json.dumps(result))

    def test_image_truncation_preserved_in_objects_and_encoded_lists(self) -> None:
        image = "data:image/png;base64," + "a" * 500
        result = routes_ai.sanitize_trace_data(
            {
                "image": image,
                "encoded": json.dumps([{"image": image, "api_key": SAMPLE_KEY}]),
            }
        )
        self.assertIn("TRUNCATED BASE64", result["image"])
        self.assertTrue(result["image"].startswith(image[:50]))
        encoded = json.loads(result["encoded"])[0]
        self.assertIn("TRUNCATED BASE64", encoded["image"])
        self.assertEqual(encoded["api_key"], REDACTED)

    def test_environment_secret_suffixes_and_bounded_credentials_file(self) -> None:
        environment = {
            "PROVIDER_API_KEY": "api-placeholder",
            "PROVIDER_ACCESS_TOKEN": "access-placeholder",
            "PROVIDER_CLIENT_SECRET": "client-placeholder",
            "PROVIDER_PRIVATE_KEY": "private-placeholder",
            "PROVIDER_TOKEN": "token-placeholder",
            "VERTEXAI_CREDENTIALS": VERTEX_KEY,
            "UNRELATED_SETTING": "ordinary-setting",
        }
        with patch.dict(os.environ, environment, clear=True):
            known = known_environment_secrets()
        for name, value in environment.items():
            if name != "UNRELATED_SETTING":
                self.assertIn(value, known)
        self.assertIn(PRIVATE_BODY, known)
        self.assertNotIn("ordinary-setting", known)
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "placeholder.json"
            for mode in ("missing", "invalid", "oversized", "directory"):
                with self.subTest(mode=mode):
                    if mode == "invalid":
                        path.write_bytes(b"invalid-json")
                    elif mode == "oversized":
                        path.write_bytes(b"x" * (1024 * 1024 + 1))
                    elif mode == "directory":
                        path.unlink()
                        path.mkdir()
                    with patch.dict(
                        os.environ,
                        {"GOOGLE_APPLICATION_CREDENTIALS": str(path)},
                        clear=True,
                    ):
                        self.assertEqual(known_environment_secrets(), (str(path),))

    def test_vertex_private_key_body_redacted_in_free_text(self) -> None:
        result = redact_secrets(
            f"error {PRIVATE_BODY} full {VERTEX_KEY}", secret_values([VERTEX_KEY])
        )
        self.assertNotIn(PRIVATE_BODY, result)
        self.assertNotIn(VERTEX_KEY, result)


if __name__ == "__main__":
    unittest.main()
