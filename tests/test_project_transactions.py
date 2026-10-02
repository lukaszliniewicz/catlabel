"""Project persistence acceptance checks using disposable SQLite databases."""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock, RLock
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import SessionTransaction
from sqlmodel import Session, SQLModel, select

from catlabel.api import routes_project as routes
from catlabel.core import database
from catlabel.core.models import Category, Project


def category(
    name: str = "Root", children: list[object] | None = None
) -> dict[str, Any]:
    return {"type": "category", "name": name, "children": children or []}


def project(name: str = "Design") -> dict[str, Any]:
    return {
        "type": "project",
        "name": name,
        "canvas_state": {"unknown": {"future": [1, 2]}, "width": 999999},
    }


class ObservedWriteLock:
    """Expose the second acquisition attempt while using a real process RLock."""

    def __init__(self) -> None:
        self.lock = RLock()
        self.counter_lock = Lock()
        self.attempts = 0
        self.second_attempt = Event()

    def __enter__(self) -> ObservedWriteLock:
        with self.counter_lock:
            self.attempts += 1
            if self.attempts == 2:
                self.second_attempt.set()
        self.lock.acquire()
        return self

    def __exit__(
        self, _exc_type: object, _exc_value: object, _traceback: object
    ) -> None:
        self.lock.release()


def route_status(action: Callable[[], object]) -> int:
    try:
        action()
    except HTTPException as exc:
        return exc.status_code
    return 200


class ProjectTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.engine = create_engine(
            f"sqlite:///{Path(tempdir.name) / 'projects.db'}",
            connect_args={"check_same_thread": False},
        )
        self.addCleanup(self.engine.dispose)
        SQLModel.metadata.create_all(self.engine)
        engine_patch = patch.object(routes, "engine", self.engine)
        engine_patch.start()
        self.addCleanup(engine_patch.stop)
        app = FastAPI()
        app.include_router(routes.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def create_project(self, **updates: Any) -> dict[str, Any]:
        payload = {
            "name": "Original",
            "canvas_state": {"text": "witness", "custom": [1, 2]},
        }
        payload.update(updates)
        response = self.client.post("/api/projects", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def seed_category(self, name: str, parent_id: int | None = None) -> int:
        with Session(self.engine) as session:
            entry = Category(name=name, parent_id=parent_id)
            session.add(entry)
            session.commit()
            session.refresh(entry)
            assert entry.id is not None
            return entry.id

    def counts(self) -> tuple[int, int]:
        with Session(self.engine) as session:
            return (
                len(session.exec(select(Category)).all()),
                len(session.exec(select(Project)).all()),
            )

    def import_tree(
        self, tree: object, target: int | None = None, version: object = "1.0"
    ):
        params = {} if target is None else {"target_category_id": target}
        return self.client.post(
            "/api/import",
            params=params,
            files={
                "file": (
                    "export.json",
                    json.dumps({"catlabel_export_version": version, "data": tree}),
                    "application/json",
                )
            },
        )

    def make_cycle(self) -> tuple[int, int]:
        first = self.seed_category("first")
        second = self.seed_category("second", first)
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE category SET parent_id = ? WHERE id = ?", (second, first)
            )
        return first, second

    def serialized_writers(
        self,
        first_action: Callable[[], object],
        second_action: Callable[[], object],
        statement_prefix: str,
    ) -> tuple[int, int]:
        first_validated = Event()
        release_first = Event()
        lock = ObservedWriteLock()

        def hold_first_write(
            connection, _cursor, statement, _parameters, context, _executemany
        ):
            if not first_validated.is_set() and statement.startswith(statement_prefix):
                first_validated.set()
                if not release_first.wait(timeout=5):
                    raise TimeoutError("Timed out waiting to release the first writer.")

        event.listen(self.engine, "before_cursor_execute", hold_first_write)
        try:
            with (
                patch.object(routes, "_project_write_lock", lock),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                first = executor.submit(route_status, first_action)
                try:
                    self.assertTrue(first_validated.wait(timeout=5))
                    second = executor.submit(route_status, second_action)
                    self.assertTrue(lock.second_attempt.wait(timeout=5))
                    self.assertFalse(second.done())
                finally:
                    release_first.set()
                return first.result(timeout=5), second.result(timeout=5)
        finally:
            event.remove(self.engine, "before_cursor_execute", hold_first_write)

    def test_opposite_category_moves_serialize_validation_and_keep_graph_acyclic(
        self,
    ) -> None:
        first_id = self.seed_category("first")
        second_id = self.seed_category("second")
        statuses = self.serialized_writers(
            lambda: routes.update_category(
                first_id, routes.CategoryUpdate(parent_id=second_id)
            ),
            lambda: routes.update_category(
                second_id, routes.CategoryUpdate(parent_id=first_id)
            ),
            "UPDATE category SET",
        )
        self.assertEqual(statuses, (200, 400))
        with Session(self.engine) as session:
            parents = {
                entry.id: entry.parent_id
                for entry in session.exec(select(Category)).all()
            }
        for category_id in parents:
            visited: set[int] = set()
            current_id = category_id
            while current_id is not None:
                self.assertNotIn(current_id, visited)
                visited.add(current_id)
                current_id = parents[current_id]

    def test_delete_category_serializes_project_creation_and_rechecks_reference(
        self,
    ) -> None:
        category_id = self.seed_category("removed")
        statuses = self.serialized_writers(
            lambda: routes.delete_category(category_id),
            lambda: routes.create_project(
                routes.ProjectCreate(
                    name="Must not be orphaned",
                    canvas_state={},
                    category_id=category_id,
                )
            ),
            "DELETE FROM category",
        )
        self.assertEqual(statuses, (200, 400))
        self.assertEqual(self.counts(), (0, 0))

    def test_create_list_detail_have_revision_and_canvas(self) -> None:
        created = self.create_project(name="  Original  ")
        self.assertEqual(created["revision"], 1)
        self.assertEqual(created["name"], "Original")
        detail = self.client.get(f"/api/projects/{created['id']}").json()
        self.assertEqual(detail["revision"], 1)
        self.assertEqual(detail["canvas_state"], {"text": "witness", "custom": [1, 2]})
        self.assertEqual(self.client.get("/api/projects").json(), [detail])
        self.assertEqual(self.client.get("/api/projects/999999").status_code, 404)

    def test_missing_and_stale_fences_preserve_all_fields(self) -> None:
        created = self.create_project()
        url = f"/api/projects/{created['id']}"
        for expected, status in ((None, 428), (2, 409)):
            body: dict[str, Any] = {"name": "Lost", "canvas_state": {"lost": True}}
            if expected is not None:
                body["expected_revision"] = expected
            response = self.client.put(url, json=body)
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["detail"]["current_revision"], 1)
            self.assertIn("message", response.json()["detail"])
            self.assertEqual(self.client.get(url).json()["name"], "Original")
        self.assertEqual(self.client.get(url).json()["canvas_state"]["text"], "witness")

    def test_revision_is_strict_positive_integer(self) -> None:
        created = self.create_project()
        for value in (True, "1", 1.0, 0, -1):
            with self.subTest(value=value):
                response = self.client.put(
                    f"/api/projects/{created['id']}",
                    json={"name": "X", "expected_revision": value},
                )
                self.assertEqual(response.status_code, 422)

    def test_metadata_only_and_noop_preserve_canvas_and_revision_rules(self) -> None:
        created = self.create_project()
        target = self.seed_category("target")
        url = f"/api/projects/{created['id']}"
        response = self.client.put(
            url, json={"name": "Renamed", "category_id": target, "expected_revision": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revision"], 2)
        self.assertEqual(
            response.json()["canvas_state_json"], created["canvas_state_json"]
        )
        self.assertEqual(
            self.client.put(url, json={"expected_revision": 2}).json()["revision"], 2
        )
        response = self.client.put(
            url,
            json={
                "category_id": None,
                "canvas_state": {"future-key": [1]},
                "expected_revision": 2,
            },
        )
        self.assertEqual(response.json()["revision"], 3)
        self.assertIsNone(response.json()["category_id"])
        self.assertEqual(
            self.client.get(url).json()["canvas_state"], {"future-key": [1]}
        )

    def test_sql_rowcount_fence_handles_a_writer_after_the_initial_read(self) -> None:
        created = self.create_project()
        url = f"/api/projects/{created['id']}"
        fired = False

        def competing_write(
            connection, _cursor, statement, _parameters, context, _executemany
        ):
            nonlocal fired
            if fired or not statement.startswith("UPDATE project SET"):
                return
            fired = True
            other_engine = create_engine(self.engine.url)
            try:
                with other_engine.begin() as other:
                    other.exec_driver_sql(
                        "UPDATE project SET name = 'Concurrent', revision = 2 WHERE id = ?",
                        (created["id"],),
                    )
            finally:
                other_engine.dispose()

        event.listen(self.engine, "before_cursor_execute", competing_write)
        try:
            response = self.client.put(
                url, json={"name": "Overwrite", "expected_revision": 1}
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", competing_write)
        self.assertTrue(fired)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["current_revision"], 2)
        self.assertEqual(self.client.get(url).json()["name"], "Concurrent")

    def test_sql_rowcount_fence_handles_deletion_after_the_initial_read(self) -> None:
        created = self.create_project()
        url = f"/api/projects/{created['id']}"
        fired = False

        def competing_delete(
            connection, _cursor, statement, _parameters, context, _executemany
        ):
            nonlocal fired
            if fired or not statement.startswith("UPDATE project SET"):
                return
            fired = True
            other_engine = create_engine(self.engine.url)
            try:
                with other_engine.begin() as other:
                    other.exec_driver_sql(
                        "DELETE FROM project WHERE id = ?", (created["id"],)
                    )
            finally:
                other_engine.dispose()

        event.listen(self.engine, "before_cursor_execute", competing_delete)
        try:
            response = self.client.put(
                url, json={"name": "Overwrite", "expected_revision": 1}
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", competing_delete)
        self.assertTrue(fired)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Project not found")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.counts(), (0, 0))

    def test_invalid_names_null_fields_and_category_references_do_not_write(
        self,
    ) -> None:
        created = self.create_project()
        url = f"/api/projects/{created['id']}"
        for body in (
            {"name": None},
            {"canvas_state": None},
            {"name": " "},
            {"name": "x" * 201},
            {"category_id": 999999},
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.client.put(
                        url, json={**body, "expected_revision": 1}
                    ).status_code,
                    400,
                )
        for name in (" ", "x" * 201):
            self.assertEqual(
                self.client.post(
                    "/api/projects", json={"name": name, "canvas_state": {}}
                ).status_code,
                400,
            )
        self.assertEqual(
            self.client.post(
                "/api/projects",
                json={"name": "X", "canvas_state": {}, "category_id": 999999},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/categories", json={"name": "X", "parent_id": 999999}
            ).status_code,
            400,
        )
        for body in (
            {"name": None, "canvas_state": {}},
            {"name": "X", "canvas_state": None},
        ):
            self.assertEqual(
                self.client.post("/api/projects", json=body).status_code, 400
            )
        self.assertEqual(
            self.client.post("/api/categories", json={"name": None}).status_code, 400
        )
        self.assertEqual(self.counts(), (0, 1))
        self.assertEqual(self.client.get(url).json()["revision"], 1)

    def test_move_missing_self_descendant_and_corrupt_ancestor_rejects_atomically(
        self,
    ) -> None:
        parent = self.seed_category("parent")
        child = self.seed_category("child", parent)
        cycle, _ = self.make_cycle()
        for new_parent in (999999, parent, child, cycle):
            with self.subTest(new_parent=new_parent):
                response = self.client.put(
                    f"/api/categories/{parent}",
                    json={"name": "Do not rename", "parent_id": new_parent},
                )
                self.assertEqual(response.status_code, 400)
                with Session(self.engine) as session:
                    saved = session.get(Category, parent)
                    assert saved is not None
                    self.assertEqual(saved.name, "parent")
                    self.assertIsNone(saved.parent_id)
        self.assertEqual(
            self.client.put(
                f"/api/categories/{child}", json={"parent_id": None}
            ).status_code,
            200,
        )

    def test_cycle_export_and_delete_fail_without_writes_and_missing_is404(
        self,
    ) -> None:
        first, _ = self.make_cycle()
        self.create_project(category_id=first)
        for method, url in (
            (self.client.get, f"/api/export?category_id={first}"),
            (self.client.delete, f"/api/categories/{first}"),
        ):
            self.assertEqual(method(url).status_code, 400)
            self.assertEqual(self.counts(), (2, 1))
        self.assertEqual(
            self.client.get("/api/export?category_id=999999").status_code, 404
        )
        self.assertEqual(self.client.delete("/api/categories/999999").status_code, 404)

    def test_root_export_rejects_unreachable_cycle_and_preserves_rows(self) -> None:
        reachable = self.seed_category("reachable")
        self.make_cycle()
        self.create_project(category_id=reachable)
        response = self.client.get("/api/export")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Stored category tree is corrupt.")
        self.assertEqual(self.counts(), (3, 1))
        self.assertEqual(
            self.client.get(f"/api/export?category_id={reachable}").status_code, 200
        )

    def test_root_export_rejects_orphan_folder_and_preserves_rows(self) -> None:
        reachable = self.seed_category("reachable")
        self.seed_category("orphan", 999999)
        response = self.client.get("/api/export")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Stored category tree is corrupt.")
        self.assertEqual(self.counts(), (2, 0))
        self.assertEqual(
            self.client.get(f"/api/export?category_id={reachable}").status_code, 200
        )

    def test_root_export_rejects_orphan_project_and_preserves_rows(self) -> None:
        reachable = self.seed_category("reachable")
        created = self.create_project()
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE project SET category_id = 999999 WHERE id = ?", (created["id"],)
            )
        response = self.client.get("/api/export")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Stored category tree is corrupt.")
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(
            self.client.get(f"/api/projects/{created['id']}").json()["category_id"],
            999999,
        )
        self.assertEqual(
            self.client.get(f"/api/export?category_id={reachable}").status_code, 200
        )

    def test_valid_export_and_delete_entire_subtree_preserve_neighbors(self) -> None:
        parent = self.seed_category("parent")
        child = self.seed_category("child", parent)
        self.seed_category("neighbor")
        self.create_project(category_id=parent)
        self.create_project(category_id=child, name="Nested")
        exported = self.client.get(f"/api/export?category_id={parent}").json()
        self.assertEqual(exported["catlabel_export_version"], "1.0")
        self.assertEqual(exported["data"]["name"], "parent")
        self.assertEqual(len(exported["data"]["children"]), 2)
        self.assertEqual(self.client.get("/api/export").json()["data"]["name"], "Root")
        self.assertEqual(
            self.client.delete(f"/api/categories/{parent}").status_code, 200
        )
        self.assertEqual(self.counts(), (1, 0))

    def test_import_rejects_every_invalid_shape_before_any_insert(self) -> None:
        invalid_nodes: list[object] = [
            None,
            [],
            {},
            {"type": "unknown", "name": "X"},
            {"type": "category", "name": "X"},
            {"type": "category", "name": "X", "children": {}},
            {"type": "project", "name": "X"},
            {"type": "project", "name": "X", "canvas_state": []},
            project(" "),
            project("x" * 201),
        ]
        insertions: list[str] = []

        def record_insert(
            connection, _cursor, statement, _parameters, context, _executemany
        ):
            if statement.startswith("INSERT"):
                insertions.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_insert)
        try:
            for node in invalid_nodes:
                with self.subTest(node=node):
                    self.assertEqual(
                        self.import_tree(
                            category("Folder", [project(), node])
                        ).status_code,
                        400,
                    )
            for payload in (
                [1],
                {"catlabel_export_version": 1.0, "data": category()},
                {"catlabel_export_version": "1.0"},
            ):
                response = self.client.post(
                    "/api/import", files={"file": ("x", json.dumps(payload))}
                )
                self.assertEqual(response.status_code, 400)
        finally:
            event.remove(self.engine, "before_cursor_execute", record_insert)
        self.assertEqual(insertions, [])
        self.assertEqual(self.counts(), (0, 0))

    def test_depth_and_node_limits_precede_writes(self) -> None:
        tree = project()
        for _ in range(routes.MAX_TREE_DEPTH + 1):
            tree = category("nested", [tree])
        self.assertEqual(self.import_tree(tree).status_code, 400)
        with patch.object(routes, "MAX_TREE_NODES", 2):
            self.assertEqual(
                self.import_tree(
                    category(children=[project("A"), project("B")])
                ).status_code,
                400,
            )
        self.assertEqual(self.counts(), (0, 0))
        tree = project()
        for _ in range(routes.MAX_TREE_DEPTH):
            tree = category("nested", [tree])
        self.assertEqual(self.import_tree(tree).status_code, 200)
        self.assertEqual(self.counts(), (64, 1))

    def test_empty_import_still_validates_target(self) -> None:
        self.assertEqual(self.import_tree(category(), target=999999).status_code, 400)
        self.assertEqual(self.counts(), (0, 0))

    def test_valid_import_preserves_canvas_counts_revision_and_root_wrapping(
        self,
    ) -> None:
        tree = category(
            children=[project("top"), category("inner", [project("nested")])]
        )
        self.assertEqual(self.import_tree(tree).status_code, 200)
        self.assertEqual(self.counts(), (1, 2))
        imported = self.client.get("/api/projects").json()
        self.assertTrue(all(item["revision"] == 1 for item in imported))
        self.assertTrue(
            all(item["canvas_state"] == project()["canvas_state"] for item in imported)
        )
        target = self.seed_category("target")
        self.assertEqual(self.import_tree(category(), target=target).status_code, 200)
        with Session(self.engine) as session:
            root = session.exec(select(Category).where(Category.name == "Root")).one()
            self.assertEqual(root.parent_id, target)
        self.assertEqual(self.counts(), (3, 2))

    def test_late_flush_and_commit_failures_roll_back_entire_import(self) -> None:
        original_flush = Session.flush
        calls = 0

        def failing_flush(session: Session, *args: Any, **kwargs: Any):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("private canvas contents from database")
            return original_flush(session, *args, **kwargs)

        tree = category("outer", [category("inner", [project()])])
        with patch.object(Session, "flush", failing_flush):
            result = self.import_tree(tree)
        self.assertEqual(calls, 2)
        self.assertEqual(result.status_code, 400)
        self.assertNotIn("private", result.text)
        self.assertEqual(self.counts(), (0, 0))
        with patch.object(
            SessionTransaction,
            "commit",
            side_effect=RuntimeError("private commit data"),
        ):
            result = self.import_tree(tree)
        self.assertEqual(result.status_code, 400)
        self.assertNotIn("private", result.text)
        self.assertEqual(self.counts(), (0, 0))

    def test_files_close_on_success_invalid_json_oversize_and_database_error(
        self,
    ) -> None:
        for mode in ("valid", "invalid", "oversize", "database"):
            raw = (
                b"bad-json"
                if mode == "invalid"
                else json.dumps(
                    {"catlabel_export_version": "1.0", "data": category("imported")}
                ).encode()
            )
            file = UploadFile(filename="x.json", file=io.BytesIO(raw))
            with self.subTest(mode=mode):
                if mode == "oversize":
                    with (
                        patch.object(routes, "MAX_UPLOAD_BYTES", 1),
                        self.assertRaises(HTTPException) as error,
                    ):
                        asyncio.run(routes.import_filesystem(file))
                    self.assertEqual(error.exception.status_code, 413)
                elif mode == "database":
                    with (
                        patch.object(
                            Session, "flush", side_effect=RuntimeError("private")
                        ),
                        self.assertRaises(HTTPException),
                    ):
                        asyncio.run(routes.import_filesystem(file))
                elif mode == "invalid":
                    with self.assertRaises(HTTPException) as error:
                        asyncio.run(routes.import_filesystem(file))
                    self.assertEqual(error.exception.status_code, 400)
                else:
                    self.assertEqual(
                        asyncio.run(routes.import_filesystem(file)),
                        {"status": "success"},
                    )
                self.assertTrue(file.file.closed)

    def test_export_and_deletion_bounds_preserve_subtree(self) -> None:
        parent = self.seed_category("parent")
        child = self.seed_category("child", parent)
        self.seed_category("grandchild", child)
        with patch.object(routes, "MAX_TREE_NODES", 2):
            self.assertEqual(
                self.client.get(f"/api/export?category_id={parent}").status_code, 400
            )
            self.assertEqual(
                self.client.delete(f"/api/categories/{parent}").status_code, 400
            )
        with patch.object(routes, "MAX_TREE_DEPTH", 1):
            self.assertEqual(
                self.client.get(f"/api/export?category_id={parent}").status_code, 400
            )
        self.assertEqual(self.counts(), (3, 0))


class ProjectMigrationTests(unittest.TestCase):
    def test_old_schema_migration_is_idempotent_and_preserves_canvas(self) -> None:
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        witness = '{ "unrecognized" : [1, {"x": "keep exact bytes"}] }'
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE project (id INTEGER PRIMARY KEY, category_id INTEGER, name VARCHAR NOT NULL, canvas_state_json VARCHAR NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO project VALUES (1, NULL, 'Witness', ?)", (witness,)
            )
        with patch.object(database, "engine", engine):
            database.create_db_and_tables()
            database.create_db_and_tables()
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT name, canvas_state_json, revision FROM project"
            ).one()
            columns = connection.exec_driver_sql("PRAGMA table_info(project)").all()
        self.assertEqual(tuple(row), ("Witness", witness, 1))
        revisions = [column for column in columns if column[1] == "revision"]
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0][3], 1)
        self.assertEqual(revisions[0][4], "1")


if __name__ == "__main__":
    unittest.main()
