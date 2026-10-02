"""Shared context preserves its projections without API-root imports or writes."""

import unittest

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from catlabel.core.models import Category, Font, LabelPreset, Project, Settings
from catlabel.services.agent_context import build_agent_context
from catlabel.services.layout_engine import TEMPLATE_METADATA


class AgentContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

    def test_absent_settings_use_defaults_without_persisting(self) -> None:
        context = build_agent_context(self.engine)
        self.assertEqual(context["global_default_font"], "RobotoCondensed.ttf")
        self.assertEqual(context["engine_rules"]["hardware_width_mm"], 48)
        self.assertEqual(context["engine_rules"]["hardware_width_px"], 383)
        self.assertEqual(context["available_templates"], TEMPLATE_METADATA)
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(Settings)).all(), [])

    def test_context_only_exposes_roots_and_projects_preset_fields(self) -> None:
        with Session(self.engine) as session:
            root = Category(name="Root")
            session.add(root)
            session.flush()
            session.add(Category(name="Nested", parent_id=root.id))
            session.add(Project(name="Root label", canvas_state_json="{}"))
            session.add(
                Project(
                    name="Nested label", category_id=root.id, canvas_state_json="{}"
                )
            )
            session.add(Font(name="Example.Bold.ttf", file_path="/unused"))
            for name in ("Zulu", "Alpha"):
                session.add(
                    LabelPreset(name=name, width_mm=30, height_mm=20, is_rotated=True)
                )
            session.add(
                Settings(default_font="Custom.ttf", default_dpi=300, print_width_mm=24)
            )
            session.commit()
        context = build_agent_context(self.engine)
        self.assertEqual([p["name"] for p in context["root_projects"]], ["Root label"])
        self.assertEqual([c["name"] for c in context["root_categories"]], ["Root"])
        self.assertEqual(context["available_fonts"], ["Example.Bold"])
        self.assertEqual(
            [p["name"] for p in context["standard_presets"]], ["Alpha", "Zulu"]
        )
        self.assertEqual(
            set(context["standard_presets"][0]),
            {"name", "media_type", "description", "width_mm", "height_mm"},
        )
        self.assertEqual(context["engine_rules"]["hardware_width_px"], 283)
        self.assertEqual(context["global_default_font"], "Custom.ttf")

    def test_empty_font_fallback_does_not_change_saved_settings(self) -> None:
        with Session(self.engine) as session:
            session.add(Settings(default_font=""))
            session.commit()
        self.assertEqual(
            build_agent_context(self.engine)["global_default_font"],
            "RobotoCondensed.ttf",
        )
        with Session(self.engine) as session:
            settings = session.get(Settings, 1)
            self.assertIsNotNone(settings)
            assert settings is not None
            self.assertEqual(settings.default_font, "")
