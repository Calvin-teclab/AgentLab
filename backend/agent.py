"""
agent.py —— Agent 核心循环(Step 4 的工业级骨架)

整个循环就 80 行。读这个文件的顺序建议:
  1. 先看最底下的 run_agent(),它是主循环
  2. 再回头看 _exec_tool_call(),它是单个工具调用的完整处理
  3. 最后看 _llm_call(),它只是薄薄一层 API 调用封装

核心设计:
  - 这是一个 ASYNC GENERATOR,每发生一步事件就 yield 一个 AgentEvent
  - 上层(main.py 的 SSE 路由)把 yield 出来的事件流推给前端
  - 这种"把循环拆成事件流"的做法,是所有可观测 agent 系统的底座
    (Cursor/Claude Code/OpenHands 都是这套架构,只是事件类型更多)
"""
import json
import os
import time
from typing import AsyncGenerator, Dict, List, Tuple

from openai import OpenAI

from schemas import AgentEvent
from tools import PolicyViolation, build_tools_schema, get_tool_impl, normalize_custom_tools


# === LLM 客户端初始化 ==================================================
# 用 OpenAI SDK 指到方舟端点。因为方舟兼容 OpenAI 协议,换 GPT/Claude 只需换环境变量。
_client = OpenAI(
    api_key=os.environ["ARK_API_KEY"],
    base_url=os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
)
_MODEL = os.environ["ARK_MODEL"]


def _rough_token_count(value) -> int:
    """
    Lightweight fallback for OpenAI-compatible providers that omit usage.

    This is intentionally approximate: CJK characters are close to one token
    each, while Latin text averages around four characters per token.
    """
    text = json.dumps(value, ensure_ascii=False, default=str)
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, cjk + (other + 3) // 4)


def _fallback_usage(messages: list, response_payload: dict) -> dict:
    prompt_tokens = _rough_token_count(messages)
    completion_tokens = _rough_token_count(response_payload)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated": True,
    }


def _llm_call(messages: list, tools_schema: list, model: str) -> dict:
    """
    调一次 LLM 并返回结构化结果。

    注意:只有启用了工具时才传 tools 参数。因为:
      1. 空的 tools=[] 某些模型会报错
      2. 不传等于告诉模型"就纯聊天",行为更稳定
    """
    t0 = time.time()
    kwargs = {"model": model, "messages": messages}
    if tools_schema:
        kwargs["tools"] = tools_schema
        kwargs["tool_choice"] = "auto"

    resp = _client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    message_dict = msg.model_dump(exclude_none=True)
    response_payload = {
        "content": msg.content,
        "tool_calls": [tc.model_dump() for tc in (msg.tool_calls or [])],
    }
    usage = resp.usage.model_dump() if resp.usage else _fallback_usage(messages, response_payload)

    return {
        "message_dict": message_dict,
        "content": msg.content,
        "tool_calls": response_payload["tool_calls"],
        "finish_reason": resp.choices[0].finish_reason,
        "usage": usage,
        "latency_s": round(time.time() - t0, 2),
    }


def _render_custom_tool_result(custom_tool: dict, args: dict) -> str:
    """Render a user-defined mock tool response for teaching tool calling."""
    template = custom_tool.get("response_template") or ""
    args_json = json.dumps(args, ensure_ascii=False, indent=2)
    if not template:
        return (
            f"[mock tool:{custom_tool['name']}]\n"
            f"收到参数:\n{args_json}\n"
            "未配置返回模板。"
        )
    rendered = (
        template
        .replace("{{tool_name}}", custom_tool["name"])
        .replace("{{args_json}}", args_json)
    )
    for key, value in args.items():
        if isinstance(value, (dict, list)):
            value_text = json.dumps(value, ensure_ascii=False)
        else:
            value_text = str(value)
        rendered = rendered.replace(f"{{{{arg.{key}}}}}", value_text)
    return rendered


def _exec_tool_call(tc: dict, custom_tools_by_name: Dict[str, dict] = None) -> Tuple[dict, str]:
    """
    执行单个 tool_call,返回 (结构化信息, 给模型看的结果字符串)。

    三层边界处理都在这里:
      1. 参数 JSON parse 失败
      2. 未知工具名(模型幻觉)
      3. 工具执行抛异常

    每一层失败都转成字符串作为"工具结果"喂回模型,不 raise 出去。
    这就是 agent 工程的核心原则:错误即 observation。
    """
    name = tc["function"]["name"]
    raw_args = tc["function"]["arguments"]

    # 边界 1: 参数 JSON parse 失败
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as e:
        return (
            {"tool": name, "status": "arg_parse_error", "raw_args": raw_args},
            f"参数解析失败:{e}。原始参数:{raw_args}",
        )

    # 边界 2: 未知工具
    impl = get_tool_impl(name)
    if impl is None and custom_tools_by_name and name in custom_tools_by_name:
        result = _render_custom_tool_result(custom_tools_by_name[name], args)
        if len(result) > 3000:
            result = result[:3000] + "\n...(mock 结果被截断)"
        return (
            {"tool": name, "args": args, "status": "mock_ok", "source": "custom"},
            result,
        )

    if impl is None:
        return (
            {"tool": name, "args": args, "status": "unknown_tool"},
            f"未知工具 {name}",
        )

    # 边界 3a: 工具层主动拒绝(代码级沙箱拦下越权请求)
    # 这是结构化信号,前端无需正则匹配中文文案即可识别"安全边界生效"。
    try:
        result = impl(**args)
    except PolicyViolation as e:
        return (
            {"tool": name, "args": args, "status": "policy_violation", "reason": str(e)},
            f"已被代码级沙箱拦截:{e}",
        )
    # 边界 3b: 工具执行异常(工具本身的 bug,不是策略拦截)
    except Exception as e:
        return (
            {"tool": name, "args": args, "status": "exec_error", "error": str(e)},
            f"工具执行异常:{e}",
        )

    # 截断过长结果,防止单次工具调用就吃掉大半 context
    if len(result) > 3000:
        result = result[:3000] + "\n...(结果被截断)"

    return (
        {"tool": name, "args": args, "status": "ok", "source": "built_in"},
        result,
    )


def _tool_call_payload(tc: dict) -> dict:
    """Return a compact, frontend-friendly tool_call payload."""
    name = tc.get("function", {}).get("name", "")
    raw_args = tc.get("function", {}).get("arguments", "")
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        args = None
    return {
        "tool_call_id": tc.get("id"),
        "tool": name,
        "raw_args": raw_args,
        "args": args,
    }


def _find_pending_tool_call(messages: List[dict]) -> dict:
    """
    Find the next unanswered tool_call in the latest assistant tool-call block.

    The OpenAI protocol requires every assistant tool_call to be followed by a
    matching tool message before the next LLM call.
    """
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            continue
        answered = {
            m.get("tool_call_id")
            for m in messages[i + 1:]
            if m.get("role") == "tool" and m.get("tool_call_id")
        }
        for tc in msg.get("tool_calls", []):
            if tc.get("id") not in answered:
                return tc
        return None
    return None


async def _process_pending_tool_calls(
    messages: List[dict],
    manual_tools: set,
    custom_tools_by_name: Dict[str, dict],
    step: int,
) -> AsyncGenerator[AgentEvent, None]:
    """
    Walk the unanswered tool_calls of the latest assistant message, in order.

    For each call:
      - if its name is in `manual_tools`: yield `tool_input_required` and stop
        (caller detects pause via _find_pending_tool_call).
      - otherwise: execute (built-in or custom mock template), append a tool
        message, yield tool_call + tool_result events.

    Pure helper; never raises. Used by both the main loop and the human-resume
    path so multi-tool-per-step calls behave identically in both directions.
    """
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            continue

        answered = {
            m.get("tool_call_id")
            for m in messages[i + 1:]
            if m.get("role") == "tool" and m.get("tool_call_id")
        }

        for tc in msg.get("tool_calls", []):
            if tc.get("id") in answered:
                continue

            tool_name = tc.get("function", {}).get("name", "")

            if tool_name in manual_tools:
                yield AgentEvent(
                    event="tool_input_required",
                    step=step,
                    data={
                        **_tool_call_payload(tc),
                        "messages_snapshot": messages,
                        "remaining_tool_calls": 1,
                    },
                )
                return

            info, result_str = _exec_tool_call(tc, custom_tools_by_name)

            yield AgentEvent(
                event="tool_call",
                step=step,
                data={"tool_call_id": tc["id"], **info},
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_str,
            })

            yield AgentEvent(
                event="tool_result",
                step=step,
                data={
                    "tool_call_id": tc["id"],
                    "tool": info["tool"],
                    "result": result_str,
                    "messages_len": len(messages),
                },
            )
        return


def _step_from_messages(messages: List[dict]) -> int:
    """Cosmetic step number for events on the resume path."""
    return sum(1 for m in messages if m.get("role") == "assistant")


async def _run_agent_loop(
    messages: List[dict],
    enabled_tools: List[str],
    max_steps: int,
    model_override: str = None,
    custom_tools: List[dict] = None,
    manual_tools: List[str] = None,
    start_step: int = 1,
) -> AsyncGenerator[AgentEvent, None]:
    """
    max_steps 是整轮预算的上限(1-indexed 的最大 step 号),不是"从 start_step 再跑几步"。
    续跑路径会传 start_step > 1,但仍用同一个 max_steps,这样人工暂停后剩余预算正确。
    """
    tools_schema = build_tools_schema(enabled_tools, custom_tools or [])
    custom_tools_by_name = normalize_custom_tools(custom_tools or [])
    manual_tools_set = set(manual_tools or [])
    model = (model_override or "").strip() or _MODEL

    for step in range(start_step, max_steps + 1):
        try:
            resp = _llm_call(messages, tools_schema, model)
        except Exception as e:
            yield AgentEvent(event="error", step=step, data={"error": str(e)})
            return

        messages.append(resp["message_dict"])

        yield AgentEvent(
            event="llm_response",
            step=step,
            data={
                "content": resp["content"],
                "tool_calls": resp["tool_calls"],
                "finish_reason": resp["finish_reason"],
                "usage": resp["usage"],
                "latency_s": resp["latency_s"],
                "messages_len": len(messages),
            },
        )

        if not resp["tool_calls"]:
            yield AgentEvent(
                event="final_answer",
                step=step,
                data={
                    "content": resp["content"],
                    "messages_snapshot": messages,
                },
            )
            return

        async for ev in _process_pending_tool_calls(
            messages, manual_tools_set, custom_tools_by_name, step
        ):
            yield ev

        # 若仍有未应答的 tool_call(命中 manual)→ 暂停等待续跑
        if _find_pending_tool_call(messages):
            return

    yield AgentEvent(
        event="max_steps",
        data={
            "max_steps": max_steps,
            "messages_snapshot": messages,
            "hint": "Agent 超过最大步数仍未给出回答,可能陷入循环。考虑调整 prompt 或增大 max_steps。",
        },
    )


async def run_agent(
    user_input: str,
    system_prompt: str,
    enabled_tools: List[str],
    max_steps: int,
    history: List[dict],
    model_override: str = None,
    custom_tools: List[dict] = None,
    manual_tools: List[str] = None,
) -> AsyncGenerator[AgentEvent, None]:
    """
    Agent 主循环。每一步事件实时 yield 出去,上层负责推给前端。

    yield 的 event 类型:
      - user_input    : 收到用户输入(带 messages 快照)
      - llm_response  : 一次 LLM 响应(含 content/tool_calls/usage)
      - tool_call     : 某个工具被调用(带参数)
      - tool_input_required : 人工模式下等待用户填写工具结果
      - tool_result   : 某个工具的执行结果
      - final_answer  : 本轮终态,给用户的自然语言回答
      - error         : LLM 调用异常等
      - max_steps     : 撞到步数上限被强制打断
    """
    # === 1. 组装 messages ==============================================
    # 如果是新会话,history 为空,放一条 system;否则直接续上。
    # 这样前端可以完全掌控"新会话/继续会话"的语义。
    if not history:
        messages = [{"role": "system", "content": system_prompt}]
    else:
        messages = list(history)  # 浅拷贝,避免污染前端传进来的对象

    messages.append({"role": "user", "content": user_input})

    yield AgentEvent(
        event="user_input",
        data={"content": user_input, "messages_snapshot": messages},
    )

    async for ev in _run_agent_loop(
        messages=messages,
        enabled_tools=enabled_tools,
        max_steps=max_steps,
        model_override=model_override,
        custom_tools=custom_tools,
        manual_tools=manual_tools,
    ):
        yield ev


async def continue_agent_after_tool(
    tool_call_id: str,
    tool_result: str,
    enabled_tools: List[str],
    max_steps: int,
    history: List[dict],
    model_override: str = None,
    custom_tools: List[dict] = None,
    manual_tools: List[str] = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Append a human-provided tool result, then continue the agent loop."""
    messages = list(history)
    pending = _find_pending_tool_call(messages)
    if not pending:
        yield AgentEvent(
            event="error",
            data={"error": "没有找到待补充结果的工具调用。请重新运行本轮任务。"},
        )
        return

    if pending.get("id") != tool_call_id:
        yield AgentEvent(
            event="error",
            data={
                "error": "提交的 tool_call_id 不是当前待处理工具调用。",
                "expected_tool_call_id": pending.get("id"),
                "received_tool_call_id": tool_call_id,
            },
        )
        return

    tool_name = pending.get("function", {}).get("name", "")
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": tool_result,
    })

    current_step = _step_from_messages(messages)

    yield AgentEvent(
        event="tool_result",
        step=current_step,
        data={
            "tool_call_id": tool_call_id,
            "tool": tool_name,
            "result": tool_result,
            "status": "human_provided",
            "source": "human",
            "messages_len": len(messages),
            "messages_snapshot": messages,
        },
    )

    # 同一个 step 里若仍有未处理的 tool_call,按"real / manual"分别处理
    custom_tools_by_name = normalize_custom_tools(custom_tools or [])
    manual_tools_set = set(manual_tools or [])

    async for ev in _process_pending_tool_calls(
        messages, manual_tools_set, custom_tools_by_name, current_step
    ):
        yield ev

    if _find_pending_tool_call(messages):
        return  # 又遇到 manual,等下一次续跑

    async for ev in _run_agent_loop(
        messages=messages,
        enabled_tools=enabled_tools,
        max_steps=max_steps,
        model_override=model_override,
        custom_tools=custom_tools,
        manual_tools=manual_tools,
        start_step=current_step + 1,
    ):
        yield ev
