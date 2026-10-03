from __future__ import annotations

import copy
import unittest
from unittest.mock import call, patch

from catlabel.api import routes_ai
from catlabel.services import ai_tools


class ManualAIResultTests(unittest.TestCase):
    def test_print_tool_only_requests_review(self) -> None:
        canvas = {"__actions__": []}
        result = ai_tools.tool_trigger_ui_action({"action": "print"}, canvas, 384, 384)
        self.assertTrue(result.startswith("Confirmation required:"))
        self.assertEqual(canvas["__actions__"], [{"action": "print_review_required"}])
        before = copy.deepcopy(canvas)
        self.assertEqual(
            ai_tools.tool_trigger_ui_action({"action": "delete"}, canvas, 384, 384),
            "Error: Unsupported UI action.",
        )
        self.assertEqual(canvas, before)

    def test_manual_results_classify_tool_strings_and_preserve_input(self) -> None:
        original_canvas = {
            "items": [{"text": "initial"}],
            "__actions__": [{"action": "existing"}],
            "metadata": {"keep": True},
        }
        original_canvas_before = copy.deepcopy(original_canvas)
        tool_calls = [
            {"tool": "ordinary"},
            {"tool": "error_string"},
            {"tool": "confirmation"},
            {"tool": "throws"},
        ]
        request = routes_ai.ManualExecuteRequest(
            tool_calls=tool_calls, canvas_state=original_canvas
        )
        returned_values = {
            "ordinary": "Saved successfully.",
            "error_string": "Error: request rejected.",
            "confirmation": "Confirmation required: review deletion.",
        }

        def execute_tool(tool_name, arguments, canvas_state):
            canvas_state["items"][0]["text"] = tool_name
            canvas_state["__actions__"].append({"tool": tool_name})
            if tool_name == "throws":
                raise RuntimeError("fixture dispatch failure")
            return returned_values[tool_name]

        with patch(
            "catlabel.api.routes_ai.execute_tool", side_effect=execute_tool
        ) as execute_tool_mock:
            actual = routes_ai.execute_manual_tools(request)

        self.assertEqual(
            actual,
            {
                "canvas_state": {
                    "items": [{"text": "throws"}],
                    "__actions__": [
                        {"action": "existing"},
                        {"tool": "ordinary"},
                        {"tool": "error_string"},
                        {"tool": "confirmation"},
                        {"tool": "throws"},
                    ],
                    "metadata": {"keep": True},
                },
                "execution_results": [
                    {
                        "index": 0,
                        "tool": "ordinary",
                        "status": "success",
                        "result": "Saved successfully.",
                    },
                    {
                        "index": 1,
                        "tool": "error_string",
                        "status": "error",
                        "result": "Error: request rejected.",
                    },
                    {
                        "index": 2,
                        "tool": "confirmation",
                        "status": "confirmation_required",
                        "result": "Confirmation required: review deletion.",
                    },
                    {
                        "index": 3,
                        "tool": "throws",
                        "status": "error",
                        "result": "fixture dispatch failure",
                    },
                ],
            },
        )
        execute_tool_mock.assert_has_calls(
            [
                call("ordinary", {}, actual["canvas_state"]),
                call("error_string", {}, actual["canvas_state"]),
                call("confirmation", {}, actual["canvas_state"]),
                call("throws", {}, actual["canvas_state"]),
            ]
        )
        self.assertEqual(original_canvas, original_canvas_before)


if __name__ == "__main__":
    unittest.main()
