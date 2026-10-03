from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlmodel import Session, SQLModel

from catlabel.api import routes_project
from catlabel.core.models import Category, Project


class ProjectSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.engine = create_engine(
            f"sqlite:///{Path(tempdir.name) / 'projects.db'}",
            connect_args={"check_same_thread": False},
        )
        self.addCleanup(self.engine.dispose)
        SQLModel.metadata.create_all(self.engine)
        engine_patch = patch.object(routes_project, "engine", self.engine)
        engine_patch.start()
        self.addCleanup(engine_patch.stop)
        app = FastAPI()
        app.include_router(routes_project.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def add_category(self, name: str = "Category") -> int:
        with Session(self.engine) as session:
            category = Category(name=name)
            session.add(category)
            session.commit()
            session.refresh(category)
            assert category.id is not None
            return category.id

    def add_projects(
        self,
        names: list[str],
        *,
        category_id: int | None = None,
        canvas_state_json: str = "{}",
    ) -> list[int]:
        with Session(self.engine) as session:
            projects = [
                Project(
                    name=name,
                    category_id=category_id,
                    canvas_state_json=canvas_state_json,
                )
                for name in names
            ]
            session.add_all(projects)
            session.commit()
            ids = [project.id for project in projects]
            assert all(project_id is not None for project_id in ids)
            return [project_id for project_id in ids if project_id is not None]

    def test_cursor_pages_are_ascending_stable_and_have_no_duplicates(self) -> None:
        category_id = self.add_category()
        expected_ids = self.add_projects(
            [f"Project {index}" for index in range(5)], category_id=category_id
        )

        first_response = self.client.get("/api/projects/summaries", params={"limit": 2})
        self.assertEqual(first_response.status_code, 200, first_response.text)
        first_page = first_response.json()
        self.assertEqual(
            [project["id"] for project in first_page["projects"]], expected_ids[:2]
        )
        self.assertEqual(first_page["next_after_id"], expected_ids[1])
        self.assertEqual(
            first_page,
            self.client.get("/api/projects/summaries", params={"limit": 2}).json(),
        )

        pages = [first_page]
        cursor = first_page["next_after_id"]
        while cursor is not None:
            response = self.client.get(
                "/api/projects/summaries", params={"limit": 2, "after_id": cursor}
            )
            self.assertEqual(response.status_code, 200, response.text)
            page = response.json()
            pages.append(page)
            cursor = page["next_after_id"]

        self.assertEqual(len(pages), 3)
        self.assertIsNone(pages[-1]["next_after_id"])
        returned_ids = [project["id"] for page in pages for project in page["projects"]]
        self.assertEqual(returned_ids, expected_ids)
        self.assertEqual(len(returned_ids), len(set(returned_ids)))
        self.assertEqual(
            [project["category_id"] for project in pages[0]["projects"]],
            [category_id, category_id],
        )
        self.assertEqual(
            set(pages[0]["projects"][0]),
            {"id", "name", "category_id", "revision"},
        )

    def test_invalid_limit_and_negative_cursor_return_422(self) -> None:
        for limit in (0, 201, "not-an-integer"):
            with self.subTest(limit=limit):
                response = self.client.get(
                    "/api/projects/summaries", params={"limit": limit}
                )
                self.assertEqual(response.status_code, 422)

        response = self.client.get("/api/projects/summaries", params={"after_id": -1})
        self.assertEqual(response.status_code, 422)

    def test_empty_summaries_return_null_cursor(self) -> None:
        response = self.client.get("/api/projects/summaries")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"projects": [], "next_after_id": None})

    def test_large_and_malformed_canvas_values_do_not_break_summaries(self) -> None:
        large_canvas = json.dumps({"payload": "x" * (2 * 1024 * 1024)})
        ids = self.add_projects(["Large", "Malformed"], canvas_state_json=large_canvas)
        with Session(self.engine) as session:
            malformed = session.get(Project, ids[1])
            assert malformed is not None
            malformed.canvas_state_json = "not valid JSON {"
            session.add(malformed)
            session.commit()

        response = self.client.get("/api/projects/summaries")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [project["id"] for project in response.json()["projects"]], ids
        )
        self.assertEqual(response.json()["next_after_id"], None)

    def test_summary_select_does_not_read_canvas_state_json(self) -> None:
        self.add_projects(["Summary"])
        statements: list[str] = []

        def capture_statement(
            _connection,
            _cursor,
            statement: str,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            normalized = statement.lower()
            if (
                normalized.lstrip().startswith("select")
                and "from project" in normalized
            ):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture_statement)
        try:
            response = self.client.get("/api/projects/summaries")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture_statement)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(statements), 1, statements)
        statement = statements[0].lower()
        self.assertNotIn("canvas_state_json", statement)
        select_clause = statement.split("from project", maxsplit=1)[0]
        self.assertIn("project.id", select_clause)
        self.assertIn("project.name", select_clause)
        self.assertIn("project.category_id", select_clause)
        self.assertIn("project.revision", select_clause)


if __name__ == "__main__":
    unittest.main()
