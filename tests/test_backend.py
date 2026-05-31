import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import agent  # noqa: E402
import tools  # noqa: E402


class CalculatorTests(unittest.TestCase):
    def test_calculator_supports_basic_arithmetic(self):
        self.assertEqual(tools.calculator("2 + 3 * 4"), "2 + 3 * 4 = 14")

    def test_calculator_supports_parentheses_and_unary(self):
        self.assertEqual(tools.calculator("-(2 + 3) * 4"), "-(2 + 3) * 4 = -20")

    def test_calculator_rejects_unsafe_syntax(self):
        result = tools.calculator("__import__('os').system('echo hacked')")
        self.assertIn("非法字符", result)

    def test_calculator_rejects_floor_and_power_ops(self):
        self.assertIn("不支持幂运算", tools.calculator("2 ** 8"))
        self.assertIn("不支持幂运算", tools.calculator("7 // 2"))


class ToolSandboxTests(unittest.TestCase):
    def test_safe_path_blocks_escape(self):
        with self.assertRaises(tools.PolicyViolation):
            tools.read_file("../../etc/passwd")

    def test_mock_tool_renders_arguments(self):
        custom_tool = {
            "name": "lookup_order",
            "description": "lookup",
            "parameters": {"type": "object", "properties": {}},
            "response_template": "tool={{tool_name}} args={{args_json}} order={{arg.order_id}}",
        }
        rendered = agent._render_custom_tool_result(custom_tool, {"order_id": "OD-123"})
        self.assertIn("tool=lookup_order", rendered)
        self.assertIn("order=OD-123", rendered)


class AgentHelperTests(unittest.IsolatedAsyncioTestCase):
    def test_classify_error_code_distinguishes_5xx_from_noise(self):
        self.assertEqual(agent._classify_error_code(Exception("HTTP 503 Service Unavailable")), "model_error")
        self.assertEqual(agent._classify_error_code(Exception("Address already in use")), "infra_error")

    async def test_process_pending_tool_calls_pauses_for_manual_tool(self):
        messages = [
            {"role": "system", "content": "test"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_current_time",
                            "arguments": "{}",
                        },
                    }
                ],
            },
        ]

        events = []
        async for ev in agent._process_pending_tool_calls(
            messages=messages,
            manual_tools={"get_current_time"},
            custom_tools_by_name={},
            step=1,
        ):
            events.append(ev)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event, "tool_input_required")
        self.assertEqual(events[0].data["tool"], "get_current_time")
        self.assertEqual(agent._find_pending_tool_call(messages)["id"], "call_1")

    async def test_process_pending_tool_calls_executes_builtin_tool(self):
        messages = [
            {"role": "system", "content": "test"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression":"2+2"}',
                        },
                    }
                ],
            },
        ]

        events = []
        async for ev in agent._process_pending_tool_calls(
            messages=messages,
            manual_tools=set(),
            custom_tools_by_name={},
            step=1,
        ):
            events.append(ev)

        self.assertEqual([ev.event for ev in events], ["tool_call", "tool_result"])
        self.assertEqual(messages[-1]["role"], "tool")
        self.assertIn("2+2 = 4", messages[-1]["content"])

    def test_exec_tool_call_includes_code_alias(self):
        info, result = agent._exec_tool_call(
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "calculator",
                    "arguments": '{"expression":"2+2"}',
                },
            }
        )
        self.assertEqual(info["status"], "ok")
        self.assertEqual(info["code"], "ok")
        self.assertIn("2+2 = 4", result)

    def test_exec_tool_call_marks_parse_error_with_code(self):
        info, result = agent._exec_tool_call(
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "calculator",
                    "arguments": "{bad-json",
                },
            }
        )
        self.assertEqual(info["status"], "arg_parse_error")
        self.assertEqual(info["code"], "arg_parse_error")
        self.assertIn("参数解析失败", result)


if __name__ == "__main__":
    unittest.main()
