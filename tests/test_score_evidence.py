import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_backend import agent, tools
from fastapi.testclient import TestClient
import main
from score_evidence import numeric_claims


def model_reply(content=None, calls=()):
    calls = [{"id": f"call_{i}", "type": "function", "function": {
        "name": name, "arguments": json.dumps(args, ensure_ascii=False)
    }} for i, (name, args) in enumerate(calls)]
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = calls
    return dict(message_dict=message, content=content, tool_calls=calls, finish_reason="stop",
                usage={}, latency_s=0, model="fixture", provider="ark")


def events(response):
    response.raise_for_status()
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


class ScoreEvidenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.scores = self.root / "scores.txt"
        self.scores.write_text("甲 90 分\n乙 75 分\n")
        self.report = self.root / "report.txt"
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        patcher = patch.object(tools, "WORKSPACE", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_case(self, case, replies, **options):
        request = dict(user_input="运行", benchmark_id=case, enabled_tools=["read_file", "write_file"])
        with patch.object(agent, "_llm_call", side_effect=replies):
            return events(self.client.post("/api/run", json={**request, **options}))

    def test_reference_is_read_from_this_workspace_before_the_run(self):
        for answer, expected in [("平均分是 99。", [99]), ("82.50 分", [82.5])]:
            stream = self.run_case("file_explore_then_read", [model_reply(answer)])
            self.assertEqual(stream[0]["data"]["score_reference"]["mean"], 82.5)
            self.assertEqual(stream[-1]["data"]["mean_claims"], expected)
        self.scores.write_text("broken")
        stream = self.run_case("file_explore_then_read", [model_reply("82.5")])
        self.assertIn("error", stream[0]["data"]["score_reference"])

    def test_report_evidence_binds_actual_file_to_this_write(self):
        report = "统计报告\n总分 165\n平均分 82.5\n最高分 90\n最低分 75\n"
        call = model_reply(calls=[("write_file", {"path": "./report.txt", "content": report})])
        stream = self.run_case("write_report", [call, model_reply("完成")])
        self.assertEqual(self.report.read_text(), report)
        result = next(e["data"] for e in stream if e["event"] == "tool_result")
        final = stream[-1]["data"]["report_evidence"]
        self.assertEqual(result["report_write_digest"], final["digest"])
        self.assertEqual(final["claims"], {"total": [165], "mean": [82.5], "max": [90], "min": [75]})
        stale = self.run_case("write_report", [model_reply("生成了 report.txt")])
        self.assertFalse(any("report_write_digest" in e["data"] for e in stale))
        # The same filename in a different directory is a different artifact.
        wrong = model_reply(calls=[("write_file", {"path": "other/report.txt", "content": report})])
        stream = self.run_case("write_report", [wrong, model_reply("完成")])
        self.assertFalse(any("report_write_digest" in e["data"] for e in stream))

    def test_manual_continuation_cannot_impersonate_a_write(self):
        self.report.write_text("平均分 82.5")
        call = model_reply(calls=[("write_file", {"path": "report.txt", "content": "平均分 82.5"})])
        paused = self.run_case("write_report", [call], manual_tools=["write_file"])
        pending = paused[-1]["data"]
        with patch.object(agent, "_llm_call", return_value=model_reply("已写入 report.txt")):
            stream = events(self.client.post("/api/continue", json={
                "tool_call_id": pending["tool_call_id"], "tool_result": "已写入 8 字符到 report.txt",
                "history": pending["messages_snapshot"], "benchmark_id": "write_report",
            }))
        self.assertFalse(any("report_write_digest" in e["data"] for e in paused + stream))
        self.assertIn("report_evidence", stream[-1]["data"])

    def test_extracts_the_conclusion_of_a_calculation(self):
        self.assertEqual(numeric_claims("平均分为：413 / 5 = 82.6 分。")["mean"], [82.6])
        self.assertEqual(numeric_claims("平均分是 82.6 + 16.4 = 99")["mean"], [99])
        self.assertEqual(numeric_claims("平均分是 82.6 + 16.4")["mean"], [])
        self.assertEqual(numeric_claims("最高分：小丽（92 分）")["max"], [92])

    def test_markdown_tables_and_conflicting_conclusions(self):
        table = "| 总分 | 平均分 | 最高分 | 最低分 |\n|---|---|---|---|\n|165|82.5|90|75|"
        self.assertEqual(numeric_claims(table), {"total": [165], "mean": [82.5], "max": [90], "min": [75]})
        self.assertEqual(numeric_claims("平均分 82.5，平均分 99")["mean"], [82.5, 99])
