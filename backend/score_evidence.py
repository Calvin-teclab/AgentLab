"""Evidence from the score fixture and the report produced by a benchmark run."""
import hashlib
import re
import unicodedata
from decimal import Decimal

from tools import _safe_path


NUMBER = r"[-+]?\d+(?:\.\d+)?"
LABELS = {
    "total": r"总分(?:数)?|总成绩|合计|total(?: score)?",
    "mean": r"平均(?:分(?:数)?|成绩|值)?|均分|average(?: score)?|mean",
    "max": r"最高(?:分(?:数)?|成绩)?|最大值|max(?:imum)?(?: score)?",
    "min": r"最低(?:分(?:数)?|成绩)?|最小值|min(?:imum)?(?: score)?",
}
SCORE_CASES = {"file_explore_then_read", "write_report"}


def read_text_file(name):
    # Fixed benchmark filenames still go through the same workspace boundary as tools.
    with _safe_path(name).open(encoding="utf-8", newline="") as stream:
        text = stream.read(100_001)
    if len(text) > 100_000:
        raise ValueError("文件超过 10 万字符")
    return text


def score_reference():
    try:
        values = []
        for line in read_text_file("scores.txt").splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(rf".+?\s+({NUMBER})\s*分?\s*", line)
            if not match:
                raise ValueError("成绩行缺少可核对的分数")
            values.append(Decimal(match[1]))
        if not values:
            raise ValueError("成绩文件为空")
        total = sum(values)
        return {k: float(v) for k, v in {
            "total": total, "mean": total / len(values),
            "max": max(values), "min": min(values),
        }.items()}
    except (OSError, UnicodeError, ValueError) as exc:
        return {"error": str(exc)}


def labelled_number(fragment, allow_name):
    fragment = fragment.lstrip(" \t|:=")
    fragment = re.sub(r"^(?:约为|等于|约|为|是)[ \t:=]*", "", fragment)
    if allow_name:
        # Reports often attach the student's name, e.g. "最高分: 小丽 (92 分)".
        fragment = re.sub(r"^[^\W\d_][\w·]{0,19}[ \t]*\([ \t]*", "", fragment)
    expression = re.match(r"[\d .()+*/×÷+\-=\t]+", fragment)
    if not expression or fragment[expression.end():].startswith(("%", "倍", "万", "e+", "e-")):
        return None
    conclusion = expression[0].rsplit("=", 1)[-1].strip().rstrip(".").strip("() ")
    return float(conclusion) if re.fullmatch(NUMBER, conclusion) else None


def numeric_claims(text, bare_mean=False):
    """Extract labelled conclusions, including row- and column-oriented Markdown tables."""
    text = unicodedata.normalize("NFKC", text or "").replace("**", "").replace("`", "")
    claims = {key: [] for key in LABELS}
    for key, label in LABELS.items():
        for match in re.finditer(label, text, re.I):
            value = labelled_number(text[match.end():match.end() + 512], key in ("max", "min"))
            if value is not None:
                claims[key].append(value)
    rows = [[v.strip() for v in line.strip().strip("|").split("|")]
            for line in text.splitlines() if "|" in line and not re.fullmatch(r"[\s|:\-]+", line)]
    for header, row in zip(rows, rows[1:]):
        if len(header) != len(row):
            continue
        for field, cell in zip(header, row):
            for key, label in LABELS.items():
                number = re.fullmatch(rf"({NUMBER})\s*分?", cell)
                if re.fullmatch(label, field, re.I) and number:
                    claims[key].append(float(number[1]))
    if bare_mean and not claims["mean"]:
        # Also accept a direct number, or the final result of a displayed calculation.
        match = re.fullmatch(rf"\s*(?:[\d\s()+*/.÷×+-]+[=＝]\s*)?({NUMBER})\s*分?\s*[。.!！]?\s*", text)
        if match:
            claims["mean"].append(float(match[1]))
    return claims


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def benchmark_events(events, case_id, enabled_tools):
    writes = {}
    async for event in events:
        data = event.data
        if event.event == "user_input":
            data["enabled_tools"] = enabled_tools
            if case_id in SCORE_CASES:
                data["score_reference"] = score_reference()
        if case_id == "write_report":
            if event.event == "tool_call" and data.get("tool") == "write_file" and data.get("source") == "built_in":
                args = data.get("args", {})
                try:
                    if _safe_path(args["path"]) == _safe_path("report.txt") and isinstance(args.get("content"), str):
                        writes[data["tool_call_id"]] = digest(args["content"])
                except (KeyError, OSError, ValueError, TypeError):
                    pass
            if event.event == "tool_result" and data.get("tool_call_id") in writes and data.get("result", "").startswith("已写入 "):
                data["report_write_digest"] = writes.pop(data["tool_call_id"])
            if event.event == "final_answer":
                try:
                    report = read_text_file("report.txt")
                    data["report_evidence"] = {"digest": digest(report), "claims": numeric_claims(report)}
                except (OSError, UnicodeError, ValueError) as exc:
                    data["report_evidence"] = {"error": str(exc)}
        if case_id == "file_explore_then_read" and event.event == "final_answer":
            data["mean_claims"] = numeric_claims(data.get("content"), bare_mean=True)["mean"]
        yield event
