"""
tools.py —— 内置工具定义

教学设计:
  每个工具 = (实现函数) + (JSON Schema 声明)
  TOOL_REGISTRY 把两者绑定在一起,供 agent 动态启用/禁用。

工具设计三原则(配合 README 食用效果最佳):
  1. 功能正交(别两个工具做重叠的事)
  2. description 写给模型看,不是给人看
  3. 错误用返回值表达,不要 raise 出去
"""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


# === 1. 安全沙箱 ======================================================
# 限制文件工具只能访问 WORKSPACE 目录下的内容,防止 agent 乱跑。
# 这是"代码级沙箱",比任何 prompt 约束都可靠。
WORKSPACE = Path(__file__).parent / "workspace"
WORKSPACE.mkdir(exist_ok=True)
TOOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class PolicyViolation(ValueError):
    """工具层主动拒绝执行(越权/沙箱越界)。

    单独的异常类型让 agent loop 能把它和普通的 exec_error 区分开,
    在事件流里挂上 status="policy_violation",前端无需正则匹配中文文案。
    """


def _safe_path(user_path: str) -> Path:
    """把用户路径限制在 WORKSPACE 内。越界 raise PolicyViolation,由上层识别。"""
    p = (WORKSPACE / user_path).resolve()
    workspace = str(WORKSPACE.resolve())
    if str(p) != workspace and not str(p).startswith(workspace + os.sep):
        raise PolicyViolation(f"路径 {user_path} 越界,禁止访问")
    return p


# === 2. 工具实现 ======================================================

def get_current_time() -> str:
    """零参数工具:演示 LLM 在需要时主动调用的行为。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def calculator(expression: str) -> str:
    """
    安全计算器:只允许数字和基本运算符。
    演示"结构化返回 + 错误转字符串喂回模型"的设计模式。
    """
    allowed = set("0123456789+-*/(). ")
    if not set(expression) <= allowed:
        # 错误作为 observation 返回,不 raise
        return f"错误:表达式包含非法字符。只允许数字和 + - * / ( ) ."
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return f"{expression} = {result}"
    except Exception as e:
        return f"计算失败:{e}"


def read_file(path: str) -> str:
    """读取 workspace 下的文件。大文件截断,防止撑爆上下文。"""
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"文件不存在:{path}"
        content = p.read_text(encoding="utf-8")
        if len(content) > 2000:
            return content[:2000] + f"\n...(文件被截断,共 {len(content)} 字符)"
        return content
    except PolicyViolation:
        raise
    except Exception as e:
        return f"读取失败:{e}"


def write_file(path: str, content: str) -> str:
    """写入文本到 workspace 下的文件,文件不存在时自动创建,已存在时覆盖。"""
    try:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {len(content)} 字符到 {path}"
    except PolicyViolation:
        raise
    except Exception as e:
        return f"写入失败:{e}"


def list_dir(path: str = ".") -> str:
    """列出 workspace 下的目录。不确定有啥文件时先调这个比 read_file 瞎猜好。"""
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"目录不存在:{path}"
        items = []
        for item in sorted(p.iterdir()):
            kind = "DIR" if item.is_dir() else "FILE"
            size = item.stat().st_size if item.is_file() else ""
            items.append(f"[{kind}] {item.name} {size}")
        return "\n".join(items) if items else "(空目录)"
    except PolicyViolation:
        raise
    except Exception as e:
        return f"列目录失败:{e}"


# === 3. 工具注册表 ====================================================
# 把"实现函数"和"JSON Schema 声明"绑在一起。
# 前端勾选工具时,后端根据这个 registry 动态构造 TOOLS_SCHEMA。
TOOL_REGISTRY: Dict[str, dict] = {
    "get_current_time": {
        "impl": get_current_time,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": (
                    "获取当前的日期和时间。"
                    "适用场景:用户询问现在几点、今天日期、当前时间。"
                    "不适用:计算未来/过去某时刻、时区转换。"
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
    },
    "calculator": {
        "impl": calculator,
        "schema": {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": (
                    "执行数学计算,支持加减乘除和括号。"
                    "适用场景:需要精确数字结果时,例如求和、平均、百分比。"
                    "不适用:矩阵运算、微积分、非数字表达式。"
                    "关键词:加减乘除、算、求、平均、百分比、sum。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "算式,只能包含数字和 + - * / ( ) .",
                        },
                    },
                    "required": ["expression"],
                },
            },
        },
    },
    "read_file": {
        "impl": read_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": (
                    "读取 workspace 目录下的文件内容。"
                    "路径是相对于 workspace 的相对路径。"
                    "文件超过 2000 字符会被截断。"
                    "适用场景:用户要求读取、查看、分析某个文件。"
                    "建议:不确定文件名时先用 list_dir 查看。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "文件相对路径,例如 'notes.txt'",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
    },
    "write_file": {
        "impl": write_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": (
                    "将文本内容写入 workspace 目录下的文件。"
                    "文件不存在时自动创建,已存在时覆盖全部内容。"
                    "路径是相对于 workspace 的相对路径。"
                    "适用场景:保存计算结果、生成报告、记录数据。"
                    "关键词:写入、保存、生成、创建文件、记录。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "文件相对路径,例如 'report.txt'",
                        },
                        "content": {
                            "type": "string",
                            "description": "要写入的完整文本内容",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
    },
    "list_dir": {
        "impl": list_dir,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": (
                    "列出 workspace 目录下的文件和子目录。"
                    "适用场景:不清楚 workspace 里有什么文件时先调用这个。"
                    "关键词:有什么文件、列出、目录、文件夹。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "目录相对路径,默认为 workspace 根目录",
                        },
                    },
                },
            },
        },
    },
}


def _normalize_custom_tool(raw: Any) -> dict:
    """把前端传入的 custom tool 转成安全、最小的工具定义。"""
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        return {}

    name = str(raw.get("name", "")).strip()
    description = str(raw.get("description", "")).strip()
    parameters = raw.get("parameters") or {"type": "object", "properties": {}}
    response_template = str(raw.get("response_template", "")).strip()

    if (
        not TOOL_NAME_RE.match(name)
        or not description
        or name in TOOL_REGISTRY
        or not isinstance(parameters, dict)
    ):
        return {}

    if parameters.get("type") != "object":
        parameters = {"type": "object", "properties": {}}

    return {
        "name": name,
        "description": description[:1200],
        "parameters": parameters,
        "response_template": response_template[:4000],
    }


def normalize_custom_tools(custom_tools: List[Any]) -> Dict[str, dict]:
    """返回 name -> custom tool。非法项会被忽略。"""
    normalized = {}
    for raw in custom_tools or []:
        tool = _normalize_custom_tool(raw)
        if tool:
            normalized[tool["name"]] = tool
    return normalized


def build_tools_schema(enabled_names: List[str], custom_tools: List[Any] = None) -> List[dict]:
    """根据前端勾选的工具名,动态构造传给 LLM 的 tools 参数。"""
    schemas = [TOOL_REGISTRY[n]["schema"] for n in enabled_names if n in TOOL_REGISTRY]
    custom_by_name = normalize_custom_tools(custom_tools or [])
    for name in enabled_names:
        custom = custom_by_name.get(name)
        if not custom:
            continue
        schemas.append({
            "type": "function",
            "function": {
                "name": custom["name"],
                "description": custom["description"],
                "parameters": custom["parameters"],
            },
        })
    return schemas


def get_tool_impl(name: str):
    """通过工具名拿实现函数。未知工具返回 None,由上层转成错误消息喂回模型。"""
    entry = TOOL_REGISTRY.get(name)
    return entry["impl"] if entry else None
