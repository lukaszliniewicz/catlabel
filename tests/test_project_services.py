from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlmodel import Session, SQLModel, select

from catlabel.core.models import Category, Project
from catlabel.services import projects
from catlabel.services.artifacts import ArtifactPin, ArtifactRecord, ArtifactStore


class ProjectServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.engine: Engine = create_engine(
            f"sqlite:///{Path(self.tempdir.name) / 'projects.db'}",
            connect_args={"check_same_thread": False},
        )
        self.addCleanup(self.engine.dispose)
        SQLModel.metadata.create_all(self.engine)

    def seed_artifact(
        self, *, mime_type: str = "image/png", expires_at: float | None = None
    ) -> str:
        now = time.time()
        artifact_id = str(uuid.uuid4())
        record = ArtifactRecord(
            id=artifact_id,
            sha256="0" * 64,
            mime_type=mime_type,
            kind="image",
            size_bytes=0,
            created_at=now,
            expires_at=now + 3600 if expires_at is None else expires_at,
        )
        with Session(self.engine) as session:
            session.add(record)
            session.commit()
        return artifact_id

    def asset_state(self, artifact_id: str) -> dict[str, Any]:
        return {
            "items": [
                {
                    "type": "group",
                    "children": [
                        {
                            "type": "image",
                            "src": f"catlabel://artifacts/{artifact_id}",
                        }
                    ],
                }
            ]
        }

    def test_concurrent_stale_revision_updates_have_one_winner(self) -> None:
        project = projects.create_project(
            projects.ProjectCreate(name="Original", canvas_state={"value": 0}),
            db_engine=self.engine,
        )
        project_id = project.id
        assert project_id is not None
        start = Barrier(2)

        def update(name: str) -> tuple[str, int, object]:
            start.wait(timeout=5)
            request = projects.ProjectUpdate(
                name=name,
                canvas_state={"value": name},
                expected_revision=1,
            )
            try:
                updated = projects.update_project(
                    project_id, request, db_engine=self.engine
                )
                return ("updated", updated.revision, updated.name)
            except projects.ProjectServiceError as exc:
                return ("error", exc.status_code, exc.detail)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(update, "First"),
                executor.submit(update, "Second"),
            ]
            results = [future.result(timeout=5) for future in futures]

        self.assertEqual(sum(result[0] == "updated" for result in results), 1)
        self.assertEqual(sum(result[0] == "error" for result in results), 1)
        conflict = next(result for result in results if result[0] == "error")
        self.assertEqual(conflict[1], 409)
        self.assertEqual(
            conflict[2],
            {
                "message": "Project changed. Reload it before saving.",
                "current_revision": 2,
            },
        )
        stored = projects.get_project(project_id, db_engine=self.engine)
        self.assertEqual(stored.revision, 2)

    def test_importing_service_does_not_import_api_package(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "import catlabel.services.projects; "
                    "assert 'catlabel.api' not in sys.modules"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_legacy_canvas_state_keeps_its_existing_shape(self) -> None:
        canvas_state = {
            "unknown": {"future": [1, 2]},
            "width": 999999,
            "items": [
                {
                    "type": "image",
                    "src": "data:image/png;base64,AA==",
                }
            ],
        }

        created = projects.create_project(
            projects.ProjectCreate(name="Legacy", canvas_state=canvas_state),
            db_engine=self.engine,
        )
        project_id = created.id
        assert project_id is not None

        self.assertEqual(created.canvas_state_json, json.dumps(canvas_state))
        self.assertEqual(
            projects.get_project_document(project_id, db_engine=self.engine)[
                "canvas_state"
            ],
            canvas_state,
        )

    def test_versioned_create_normalizes_and_rejects_invalid_documents(self) -> None:
        canonical_input = {
            "document_version": 1,
            "items": [{"id": "text-1", "type": "text"}],
        }
        created = projects.create_project(
            projects.ProjectCreate(name="Canonical", canvas_state=canonical_input),
            db_engine=self.engine,
        )
        saved_state = json.loads(created.canvas_state_json)
        self.assertEqual(saved_state["document_version"], 1)
        self.assertEqual(saved_state["dpi"], 203)
        self.assertEqual(saved_state["items"][0]["id"], "text-1")
        self.assertEqual(
            canonical_input,
            {
                "document_version": 1,
                "items": [{"id": "text-1", "type": "text"}],
            },
        )

        invalid_states: list[tuple[str, dict[str, Any]]] = [
            ("unsupported version", {"document_version": 2, "items": []}),
            (
                "invalid id",
                {
                    "document_version": 1,
                    "items": [{"id": "", "type": "text"}],
                },
            ),
            (
                "nonfinite geometry",
                {
                    "document_version": 1,
                    "items": [
                        {"id": "text-2", "type": "text", "rotation": float("nan")}
                    ],
                },
            ),
        ]
        for label, invalid_state in invalid_states:
            with self.subTest(document=label):
                with self.assertRaises(projects.ProjectServiceError) as error:
                    projects.create_project(
                        projects.ProjectCreate(
                            name="Invalid", canvas_state=invalid_state
                        ),
                        db_engine=self.engine,
                    )
                self.assertEqual(error.exception.status_code, 400)
                self.assertIsInstance(error.exception.detail, str)

        with Session(self.engine) as session:
            saved_projects = session.exec(select(Project)).all()
        self.assertEqual(len(saved_projects), 1)

    def test_invalid_versioned_updates_do_not_change_document_or_revision(self) -> None:
        created = projects.create_project(
            projects.ProjectCreate(
                name="Original", canvas_state={"legacy": "unchanged"}
            ),
            db_engine=self.engine,
        )
        project_id = created.id
        assert project_id is not None
        original_state = created.canvas_state_json
        invalid_states = [
            {"document_version": 1, "items": [{"id": "", "type": "text"}]},
            {
                "document_version": 1,
                "items": [{"id": "text-1", "type": "text", "rotation": float("inf")}],
            },
        ]

        for invalid_state in invalid_states:
            with self.subTest(document=invalid_state):
                with self.assertRaises(projects.ProjectServiceError) as error:
                    projects.update_project(
                        project_id,
                        projects.ProjectUpdate(
                            canvas_state=invalid_state, expected_revision=1
                        ),
                        db_engine=self.engine,
                    )
                self.assertEqual(error.exception.status_code, 400)
                current = projects.get_project(project_id, db_engine=self.engine)
                self.assertEqual(current.revision, 1)
                self.assertEqual(current.canvas_state_json, original_state)

    def test_import_validates_versioned_documents_before_any_insert(self) -> None:
        invalid_tree = {
            "type": "category",
            "name": "Root",
            "children": [
                {
                    "type": "project",
                    "name": "Invalid design",
                    "canvas_state": {
                        "document_version": 1,
                        "items": [
                            {"id": "same", "type": "text"},
                            {"id": "same", "type": "text"},
                        ],
                    },
                }
            ],
        }

        with self.assertRaises(projects.ProjectServiceError) as error:
            projects.import_tree(invalid_tree, None, db_engine=self.engine)

        self.assertEqual(error.exception.status_code, 400)
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(Category)).all(), [])
            self.assertEqual(session.exec(select(Project)).all(), [])

    def test_import_normalizes_versioned_documents_without_mutating_input(self) -> None:
        canvas_state = {
            "document_version": 1,
            "items": [{"id": "imported-1", "type": "text"}],
        }
        tree = {
            "type": "category",
            "name": "Root",
            "children": [
                {
                    "type": "project",
                    "name": "Imported",
                    "canvas_state": canvas_state,
                }
            ],
        }

        projects.import_tree(tree, None, db_engine=self.engine)

        saved = projects.list_projects(db_engine=self.engine)[0]
        self.assertEqual(saved["canvas_state"]["document_version"], 1)
        self.assertEqual(saved["canvas_state"]["dpi"], 203)
        self.assertEqual(canvas_state, tree["children"][0]["canvas_state"])

    def test_managed_asset_pins_survive_artifact_expiry_and_reap(self) -> None:
        artifact_id = self.seed_artifact()
        project = projects.create_project(
            projects.ProjectCreate(
                name="Pinned", canvas_state=self.asset_state(artifact_id)
            ),
            db_engine=self.engine,
        )
        project_id = project.id
        assert project_id is not None
        owner = f"design:{project_id}"

        with Session(self.engine) as session:
            record = session.get(ArtifactRecord, artifact_id)
            assert record is not None
            record.expires_at = time.time() - 1
            session.add(record)
            session.commit()
            pin = session.get(ArtifactPin, (owner, artifact_id))
            self.assertIsNotNone(pin)
            assert pin is not None
            self.assertIsNone(pin.expires_at)

        updated = projects.update_project(
            project_id,
            projects.ProjectUpdate(
                name="Edited",
                canvas_state=self.asset_state(artifact_id),
                expected_revision=1,
            ),
            db_engine=self.engine,
        )
        self.assertEqual((updated.name, updated.revision), ("Edited", 2))

        copied = projects.create_project(
            projects.ProjectCreate(
                name="Copy", canvas_state=self.asset_state(artifact_id)
            ),
            db_engine=self.engine,
        )
        assert copied.id is not None
        copy_owner = f"design:{copied.id}"
        with Session(self.engine) as session:
            self.assertIsNotNone(session.get(ArtifactPin, (copy_owner, artifact_id)))

        store = ArtifactStore(
            self.engine, Path(self.tempdir.name) / "managed-artifacts"
        )
        self.addCleanup(store.close)
        self.assertEqual(store.reap(), 0)
        with Session(self.engine) as session:
            self.assertIsNotNone(session.get(ArtifactRecord, artifact_id))
            self.assertIsNotNone(session.get(ArtifactPin, (owner, artifact_id)))
            self.assertIsNotNone(session.get(ArtifactPin, (copy_owner, artifact_id)))

    def test_missing_expired_and_non_png_assets_roll_back_project_create(self) -> None:
        expired_id = self.seed_artifact(expires_at=time.time() - 1)
        missing_id = str(uuid.uuid4())
        jpeg_id = self.seed_artifact(mime_type="image/jpeg")
        for artifact_id in (expired_id, missing_id, jpeg_id, "not-a-uuid"):
            with self.subTest(artifact_id=artifact_id):
                with self.assertRaises(projects.ProjectServiceError) as error:
                    projects.create_project(
                        projects.ProjectCreate(
                            name="Rejected", canvas_state=self.asset_state(artifact_id)
                        ),
                        db_engine=self.engine,
                    )
                self.assertEqual(error.exception.status_code, 400)

        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(Project)).all(), [])
            self.assertEqual(session.exec(select(ArtifactPin)).all(), [])

    def test_create_and_import_pin_managed_assets_for_each_design(self) -> None:
        artifact_id = self.seed_artifact()
        state = self.asset_state(artifact_id)
        created = projects.create_project(
            projects.ProjectCreate(name="Original", canvas_state=state),
            db_engine=self.engine,
        )
        copied = projects.create_project(
            projects.ProjectCreate(name="Copy", canvas_state=state),
            db_engine=self.engine,
        )
        tree = {
            "type": "category",
            "name": "Root",
            "children": [
                {
                    "type": "project",
                    "name": "Imported",
                    "canvas_state": state,
                }
            ],
        }
        projects.import_tree(tree, None, db_engine=self.engine)
        imported = projects.list_projects(db_engine=self.engine)[-1]

        for project_id in (created.id, copied.id, imported["id"]):
            assert project_id is not None
            with Session(self.engine) as session:
                self.assertIsNotNone(
                    session.get(
                        ArtifactPin,
                        (f"design:{project_id}", artifact_id),
                    )
                )

    def test_update_replaces_and_removing_managed_asset_releases_pin(self) -> None:
        artifact_id = self.seed_artifact()
        replacement_id = self.seed_artifact()
        project = projects.create_project(
            projects.ProjectCreate(
                name="Pinned", canvas_state=self.asset_state(artifact_id)
            ),
            db_engine=self.engine,
        )
        project_id = project.id
        assert project_id is not None

        updated = projects.update_project(
            project_id,
            projects.ProjectUpdate(
                canvas_state=self.asset_state(replacement_id), expected_revision=1
            ),
            db_engine=self.engine,
        )

        self.assertEqual(updated.revision, 2)
        with Session(self.engine) as session:
            self.assertIsNone(
                session.get(ArtifactPin, (f"design:{project_id}", artifact_id))
            )
            self.assertIsNotNone(
                session.get(ArtifactPin, (f"design:{project_id}", replacement_id))
            )

        updated = projects.update_project(
            project_id,
            projects.ProjectUpdate(canvas_state={"items": []}, expected_revision=2),
            db_engine=self.engine,
        )

        self.assertEqual(updated.revision, 3)
        with Session(self.engine) as session:
            self.assertIsNone(
                session.get(ArtifactPin, (f"design:{project_id}", replacement_id))
            )

    def test_missing_managed_asset_update_rolls_back_project_and_pins(self) -> None:
        artifact_id = self.seed_artifact()
        project = projects.create_project(
            projects.ProjectCreate(
                name="Pinned", canvas_state=self.asset_state(artifact_id)
            ),
            db_engine=self.engine,
        )
        project_id = project.id
        assert project_id is not None
        missing_id = str(uuid.uuid4())

        with self.assertRaises(projects.ProjectServiceError) as error:
            projects.update_project(
                project_id,
                projects.ProjectUpdate(
                    name="Must roll back",
                    canvas_state=self.asset_state(missing_id),
                    expected_revision=1,
                ),
                db_engine=self.engine,
            )

        self.assertEqual(error.exception.status_code, 400)
        current = projects.get_project(project_id, db_engine=self.engine)
        self.assertEqual(current.name, "Pinned")
        self.assertEqual(current.revision, 1)
        with Session(self.engine) as session:
            self.assertIsNotNone(
                session.get(ArtifactPin, (f"design:{project_id}", artifact_id))
            )
            self.assertIsNone(
                session.get(ArtifactPin, (f"design:{project_id}", missing_id))
            )

    def test_missing_managed_asset_import_rolls_back_tree(self) -> None:
        tree = {
            "type": "category",
            "name": "Imported Root",
            "children": [
                {
                    "type": "project",
                    "name": "Rejected",
                    "canvas_state": self.asset_state(str(uuid.uuid4())),
                }
            ],
        }

        with self.assertRaises(projects.ProjectServiceError) as error:
            projects.import_tree(tree, None, db_engine=self.engine)

        self.assertEqual(error.exception.status_code, 400)
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(Category)).all(), [])
            self.assertEqual(session.exec(select(Project)).all(), [])
            self.assertEqual(session.exec(select(ArtifactPin)).all(), [])

    def test_project_and_category_deletion_release_asset_pins(self) -> None:
        direct_artifact_id = self.seed_artifact()
        direct = projects.create_project(
            projects.ProjectCreate(
                name="Direct", canvas_state=self.asset_state(direct_artifact_id)
            ),
            db_engine=self.engine,
        )
        direct_id = direct.id
        assert direct_id is not None
        projects.delete_project(direct_id, db_engine=self.engine)

        category = projects.create_category(
            projects.CategoryCreate(name="Cascade"), db_engine=self.engine
        )
        category_id = category.id
        assert category_id is not None
        cascade_artifact_id = self.seed_artifact()
        cascaded = projects.create_project(
            projects.ProjectCreate(
                name="Cascaded",
                category_id=category_id,
                canvas_state=self.asset_state(cascade_artifact_id),
            ),
            db_engine=self.engine,
        )
        cascaded_id = cascaded.id
        assert cascaded_id is not None
        projects.delete_category(category_id, db_engine=self.engine)

        with Session(self.engine) as session:
            self.assertIsNone(
                session.get(ArtifactPin, (f"design:{direct_id}", direct_artifact_id))
            )
            self.assertIsNone(
                session.get(ArtifactPin, (f"design:{cascaded_id}", cascade_artifact_id))
            )
            self.assertIsNone(session.get(Project, cascaded_id))


if __name__ == "__main__":
    unittest.main()
