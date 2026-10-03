from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from catlabel.api import routes_project
from catlabel.core.models import Project
from catlabel.services import ai_tools


class ProjectToolRevisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine: Engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        database_engine_patch = patch("catlabel.core.database.engine", self.engine)
        routes_engine_patch = patch("catlabel.api.routes_project.engine", self.engine)
        database_engine_patch.start()
        routes_engine_patch.start()
        self.addCleanup(routes_engine_patch.stop)
        self.addCleanup(database_engine_patch.stop)
        self.addCleanup(self.engine.dispose)

    def test_save_load_and_update_follow_api_revision_contract(self) -> None:
        canvas_state = {
            "items": [{"text": "saved"}],
            "custom": "original",
            "__actions__": [{"action": "old_action"}],
            "__project_id__": 900,
            "__project_revision__": 99,
        }

        save_result = ai_tools.tool_save_project(
            {"name": "Original"}, canvas_state, 384, 384
        )
        self.assertIn("successfully saved", save_result)
        project_id = canvas_state["__project_id__"]
        self.assertIsInstance(project_id, int)
        self.assertEqual(canvas_state["__project_revision__"], 1)

        stored = routes_project.get_project(project_id)
        self.assertEqual(stored["revision"], 1)
        self.assertEqual(
            stored["canvas_state"],
            {"items": [{"text": "saved"}], "custom": "original"},
        )
        self.assertEqual(
            canvas_state["__actions__"],
            [
                {"action": "old_action"},
                {
                    "action": "loaded_project_id",
                    "project_id": project_id,
                    "revision": 1,
                },
                {"action": "refresh_projects"},
            ],
        )

        canvas_state["custom"] = "unsaved mutation"
        load_result = ai_tools.tool_load_project(
            {"project_id": project_id}, canvas_state, 384, 384
        )
        self.assertIn("Successfully loaded", load_result)
        self.assertEqual(canvas_state["custom"], "original")
        self.assertEqual(canvas_state["__project_id__"], project_id)
        self.assertEqual(canvas_state["__project_revision__"], 1)
        self.assertEqual(
            canvas_state["__actions__"],
            [{"action": "loaded_project_id", "project_id": project_id, "revision": 1}],
        )

        canvas_state["custom"] = "updated"
        update_result = ai_tools.tool_update_project(
            {"project_id": project_id, "name": "Renamed"},
            canvas_state,
            384,
            384,
        )
        self.assertIn("Successfully updated", update_result)
        self.assertEqual(canvas_state["__project_revision__"], 2)
        stored = routes_project.get_project(project_id)
        self.assertEqual(stored["name"], "Renamed")
        self.assertEqual(stored["revision"], 2)
        self.assertEqual(
            stored["canvas_state"],
            {"items": [{"text": "saved"}], "custom": "updated"},
        )
        self.assertEqual(
            canvas_state["__actions__"][-2:],
            [
                {
                    "action": "loaded_project_id",
                    "project_id": project_id,
                    "revision": 2,
                },
                {"action": "refresh_projects"},
            ],
        )

    def test_stale_update_preserves_canvas_and_database(self) -> None:
        canvas_state: dict[str, object] = {"items": [{"text": "draft"}]}
        ai_tools.tool_save_project({"name": "Project"}, canvas_state, 384, 384)
        project_id = canvas_state["__project_id__"]
        self.assertIsInstance(project_id, int)
        assert isinstance(project_id, int)

        routes_project.update_project(
            project_id,
            routes_project.ProjectUpdate.model_validate(
                {"expected_revision": 1, "canvas_state": {"external": "newer"}}
            ),
        )
        database_after_concurrent_update = routes_project.get_project(project_id)
        canvas_before_tool_update = copy.deepcopy(canvas_state)

        result = ai_tools.tool_update_project(
            {"project_id": project_id}, canvas_state, 384, 384
        )

        self.assertTrue(result.startswith("Error:"))
        self.assertIn("Reload", result)
        self.assertIn("review", result)
        self.assertEqual(canvas_state, canvas_before_tool_update)
        self.assertEqual(
            routes_project.get_project(project_id), database_after_concurrent_update
        )

    def test_wrong_target_and_invalid_revision_are_rejected_without_mutation(
        self,
    ) -> None:
        first_id = self._create_project("First", {"items": ["first"]})
        second_id = self._create_project("Second", {"items": ["second"]})
        canvas_state: dict[str, object] = {"__actions__": [{"action": "keep"}]}
        ai_tools.tool_load_project({"project_id": first_id}, canvas_state, 384, 384)

        projects_before = [
            routes_project.get_project(first_id),
            routes_project.get_project(second_id),
        ]
        canvas_before = copy.deepcopy(canvas_state)
        wrong_target_result = ai_tools.tool_update_project(
            {"project_id": second_id}, canvas_state, 384, 384
        )
        self.assertEqual(
            wrong_target_result,
            "Error: Load the target saved project before updating it.",
        )
        self.assertEqual(canvas_state, canvas_before)
        self.assertEqual(
            [
                routes_project.get_project(first_id),
                routes_project.get_project(second_id),
            ],
            projects_before,
        )

        for invalid_revision in (None, 0, -1, True, 1.0, "1"):
            with self.subTest(revision=invalid_revision):
                canvas_state["__project_revision__"] = invalid_revision
                canvas_before = copy.deepcopy(canvas_state)
                result = ai_tools.tool_update_project(
                    {"project_id": first_id}, canvas_state, 384, 384
                )
                self.assertEqual(
                    result,
                    "Error: Load the target saved project before updating it.",
                )
                self.assertEqual(canvas_state, canvas_before)

        canvas_state.pop("__project_revision__")
        canvas_before = copy.deepcopy(canvas_state)
        missing_revision_result = ai_tools.tool_update_project(
            {"project_id": first_id}, canvas_state, 384, 384
        )
        self.assertEqual(
            missing_revision_result,
            "Error: Load the target saved project before updating it.",
        )
        self.assertEqual(canvas_state, canvas_before)

    def test_clear_canvas_invalidates_only_project_identity_keys(self) -> None:
        canvas_state = {
            "items": [{"text": "clear"}],
            "currentPage": 3,
            "pageLayouts": [{"pageIndex": 3, "htmlContent": "old"}],
            "custom": "keep",
            "__actions__": [{"action": "keep"}],
            "__project_id__": 4,
            "__project_revision__": 7,
        }

        ai_tools.tool_clear_canvas({}, canvas_state, 384, 384)

        self.assertNotIn("__project_id__", canvas_state)
        self.assertNotIn("__project_revision__", canvas_state)
        self.assertEqual(canvas_state["custom"], "keep")
        self.assertEqual(canvas_state["__actions__"], [{"action": "keep"}])
        self.assertEqual(canvas_state["items"], [])
        self.assertEqual(canvas_state["currentPage"], 0)
        self.assertEqual(
            canvas_state["pageLayouts"],
            [{"pageIndex": 0, "htmlContent": "", "activeTemplate": None}],
        )

    def test_category_and_project_tools_defer_saved_deletion(self) -> None:
        canvas_state = {"__actions__": []}
        with patch.object(
            routes_project,
            "create_category",
            wraps=routes_project.create_category,
        ) as create_category_api:
            create_result = ai_tools.tool_create_category(
                {"name": "Parent"}, canvas_state, 384, 384
            )
            create_category_api.assert_called_once()
        self.assertIn("created with ID", create_result)

        parent_category = next(
            category
            for category in routes_project.list_categories()
            if category.name == "Parent"
        )
        assert parent_category.id is not None
        parent_id = parent_category.id

        actions_before_invalid_create = copy.deepcopy(canvas_state["__actions__"])
        invalid_create = ai_tools.tool_create_category(
            {"name": []}, canvas_state, 384, 384
        )
        self.assertTrue(invalid_create.startswith("Error:"))
        self.assertEqual(canvas_state["__actions__"], actions_before_invalid_create)

        invalid_parent = ai_tools.tool_create_category(
            {"name": "Invalid child", "parent_id": 99_999},
            canvas_state,
            384,
            384,
        )
        self.assertTrue(invalid_parent.startswith("Error:"))
        self.assertEqual(canvas_state["__actions__"], actions_before_invalid_create)

        child_result = ai_tools.tool_create_category(
            {"name": "Child", "parent_id": parent_id}, canvas_state, 384, 384
        )
        self.assertIn("created with ID", child_result)
        child_category = next(
            category
            for category in routes_project.list_categories()
            if category.name == "Child"
        )
        assert child_category.id is not None

        project_to_delete = routes_project.create_project(
            routes_project.ProjectCreate(
                name="Direct delete",
                canvas_state={"value": "one"},
                category_id=parent_id,
            )
        )
        recursive_project = routes_project.create_project(
            routes_project.ProjectCreate(
                name="Recursive delete",
                canvas_state={"value": "two"},
                category_id=child_category.id,
            )
        )
        neighbor_category = routes_project.create_category(
            routes_project.CategoryCreate(name="Neighbor")
        )
        assert neighbor_category.id is not None
        neighbor_project = routes_project.create_project(
            routes_project.ProjectCreate(
                name="Neighbor project",
                canvas_state={"value": "neighbor"},
                category_id=neighbor_category.id,
            )
        )
        assert project_to_delete.id is not None
        assert recursive_project.id is not None
        assert neighbor_project.id is not None

        with (
            patch.object(
                routes_project,
                "delete_project",
                side_effect=AssertionError("AI tools must defer project deletion"),
            ) as delete_project_api,
            patch.object(
                routes_project,
                "delete_category",
                side_effect=AssertionError("AI tools must defer folder deletion"),
            ) as delete_category_api,
        ):
            refresh_actions_before = [
                action
                for action in canvas_state["__actions__"]
                if action.get("action") == "refresh_projects"
            ]
            delete_result = ai_tools.tool_delete_project(
                {"project_id": project_to_delete.id}, canvas_state, 384, 384
            )
            self.assertEqual(
                delete_result,
                ai_tools._AI_DELETION_REVIEW_MESSAGE.format(
                    kind="project",
                    name="Direct delete",
                    target_id=project_to_delete.id,
                ),
            )
            project_review_action = {
                "action": "deletion_review_required",
                "target_kind": "project",
                "target_id": project_to_delete.id,
                "name": "Direct delete",
            }
            self.assertEqual(canvas_state["__actions__"][-1], project_review_action)

            actions_after_project_review = copy.deepcopy(canvas_state["__actions__"])
            repeated_project_review = ai_tools.tool_delete_project(
                {"project_id": project_to_delete.id}, canvas_state, 384, 384
            )
            self.assertEqual(repeated_project_review, delete_result)
            self.assertEqual(canvas_state["__actions__"], actions_after_project_review)

            category_result = ai_tools.tool_delete_category(
                {"category_id": parent_id}, canvas_state, 384, 384
            )
            self.assertEqual(
                category_result,
                ai_tools._AI_DELETION_REVIEW_MESSAGE.format(
                    kind="folder", name="Parent", target_id=parent_id
                ),
            )
            category_review_action = {
                "action": "deletion_review_required",
                "target_kind": "folder",
                "target_id": parent_id,
                "name": "Parent",
            }
            self.assertEqual(canvas_state["__actions__"][-1], category_review_action)

            actions_after_category_review = copy.deepcopy(canvas_state["__actions__"])
            repeated_category_review = ai_tools.tool_delete_category(
                {"category_id": parent_id}, canvas_state, 384, 384
            )
            self.assertEqual(repeated_category_review, category_result)
            self.assertEqual(canvas_state["__actions__"], actions_after_category_review)

            actions_before_missing = copy.deepcopy(canvas_state["__actions__"])
            self.assertEqual(
                ai_tools.tool_delete_project(
                    {"project_id": 999_999}, canvas_state, 384, 384
                ),
                ai_tools._AI_DELETION_MISSING_PROJECT,
            )
            self.assertEqual(
                ai_tools.tool_delete_category(
                    {"category_id": 999_999}, canvas_state, 384, 384
                ),
                ai_tools._AI_DELETION_MISSING_CATEGORY,
            )
            self.assertEqual(canvas_state["__actions__"], actions_before_missing)

            invalid_cases = (
                (
                    ai_tools.tool_delete_project,
                    "project_id",
                    project_to_delete.id,
                    ai_tools._AI_DELETION_INVALID_PROJECT,
                ),
                (
                    ai_tools.tool_delete_category,
                    "category_id",
                    child_category.id,
                    ai_tools._AI_DELETION_INVALID_CATEGORY,
                ),
            )
            for delete_tool, id_key, valid_id, expected_error in invalid_cases:
                for invalid_id in (None, 0, -1, True, float(valid_id), str(valid_id)):
                    with self.subTest(id_key=id_key, invalid_id=invalid_id):
                        actions_before_invalid = copy.deepcopy(
                            canvas_state["__actions__"]
                        )
                        self.assertEqual(
                            delete_tool({id_key: invalid_id}, canvas_state, 384, 384),
                            expected_error,
                        )
                        self.assertEqual(
                            canvas_state["__actions__"], actions_before_invalid
                        )

            delete_project_api.assert_not_called()
            delete_category_api.assert_not_called()

            refresh_actions_after = [
                action
                for action in canvas_state["__actions__"]
                if action.get("action") == "refresh_projects"
            ]
            self.assertEqual(refresh_actions_after, refresh_actions_before)

        categories_by_id = {
            category.id: category for category in routes_project.list_categories()
        }
        self.assertEqual(
            {parent_id, child_category.id, neighbor_category.id}
            & categories_by_id.keys(),
            {parent_id, child_category.id, neighbor_category.id},
        )
        projects_by_id = {
            project["id"]: project for project in routes_project.list_projects()
        }
        self.assertEqual(
            {
                project_to_delete.id,
                recursive_project.id,
                neighbor_project.id,
            }
            & projects_by_id.keys(),
            {
                project_to_delete.id,
                recursive_project.id,
                neighbor_project.id,
            },
        )
        self.assertEqual(
            projects_by_id[project_to_delete.id]["canvas_state"], {"value": "one"}
        )
        self.assertEqual(
            projects_by_id[recursive_project.id]["canvas_state"], {"value": "two"}
        )
        self.assertEqual(
            projects_by_id[neighbor_project.id]["canvas_state"],
            {"value": "neighbor"},
        )

    def _create_project(self, name: str, canvas_state: dict[str, object]) -> int:
        project: Project = routes_project.create_project(
            routes_project.ProjectCreate(name=name, canvas_state=canvas_state)
        )
        self.assertIsNotNone(project.id)
        assert project.id is not None
        return project.id


if __name__ == "__main__":
    unittest.main()
