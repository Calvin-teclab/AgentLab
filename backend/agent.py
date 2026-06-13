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
import asyncio
import json
import os
import re
import time
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from openai import OpenAI

from schemas import AgentEvent
from tools import PolicyViolation, build_tools_schema, get_tool_impl, normalize_custom_tools


# === Provider 注册表(多家 LLM 备选) ==================================
# 设计:每家厂商提供一组 env 三件套 (API_KEY / MODEL / BASE_URL),
# 客户端按需 lazy 创建。这样只配了其中一家也能启动,不会因为缺另一家的 key 直接崩。
#
# Ark   : 火山方舟,OpenAI 协议原生兼容
# Gemini: 用 Google 的 OpenAI 兼容端点 (v1beta/openai/),无需新 SDK
#         (https://ai.google.dev/gemini-api/docs/openai)
_PROVIDER_CONFIG = {
    "ark": {
        "api_key_env": "ARK_API_KEY",
        "model_env": "ARK_MODEL",
        "base_url_env": "ARK_BASE_URL",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": None,  # 必须显式配置
        "label": "火山方舟 (DeepSeek 等)",
    },
    "gemini": {
        "api_key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "base_url_env": "GEMINI_BASE_URL",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-flash-latest",
        "label": "Google Gemini",
    },
}

_DEFAULT_PROVIDER = "ark"

# 已创建的客户端缓存:provider → OpenAI client
_clients: Dict[str, OpenAI] = {}

EVENT_PROTOCOL_VERSION = 1


def _is_real_key(value: str) -> bool:
    """过滤掉 .env.example 拷过来的占位符,避免前端把没真配的 provider 也显示出来。"""
    if not value:
        return False
    v = value.strip().lower()
    return not (
        v.startswith("your_")
        or v.endswith("_here")
        or "api_key_here" in v
        or v in {"changeme", "xxx", "todo"}
    )


def list_configured_providers() -> List[Dict[str, str]]:
    """返回当前 .env 中已配 API Key 的 provider 列表(供前端切换 UI 使用)。"""
    result = []
    for name, cfg in _PROVIDER_CONFIG.items():
        if _is_real_key(os.environ.get(cfg["api_key_env"], "")):
            result.append({
                "name": name,
                "label": cfg["label"],
                "default_model": os.environ.get(cfg["model_env"]) or cfg["default_model"] or "",
            })
    return result


def _get_client_and_model(provider: str, model_override: str = None) -> Tuple[OpenAI, str]:
    """按 provider 解析出 (OpenAI client, model 名)。客户端 lazy 创建并缓存。"""
    provider = (provider or "").strip().lower() or _DEFAULT_PROVIDER
    if provider not in _PROVIDER_CONFIG:
        raise ValueError(f"未知的 provider: {provider}。可选:{list(_PROVIDER_CONFIG)}")

    cfg = _PROVIDER_CONFIG[provider]
    api_key = os.environ.get(cfg["api_key_env"])
    if not api_key:
        raise RuntimeError(
            f"provider={provider} 未配置:请在 backend/.env 中设置 {cfg['api_key_env']}。"
        )

    if provider not in _clients:
        _clients[provider] = OpenAI(
            api_key=api_key,
            base_url=os.environ.get(cfg["base_url_env"], cfg["default_base_url"]),
            # SDK 默认 600s,对交互式 SSE 流太长了:上游卡住会让整条时间轴干等
            # 十分钟。教学场景设短一些,超时直接转成 error 事件喂回前端。
            timeout=60,
        )

    model = (model_override or "").strip() \
        or os.environ.get(cfg["model_env"]) \
        or cfg["default_model"] \
        or ""
    if not model:
        raise RuntimeError(
            f"provider={provider} 未指定模型:请在 .env 中设置 {cfg['model_env']},或在前端填 Endpoint 覆盖。"
        )

    return _clients[provider], model


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


def _classify_error_code(exc: Exception) -> str:
    """Best-effort error code for transport/provider/runtime failures."""
    s = str(exc).lower()
    if any(token in s for token in ("api key", "apikey", "401", "403", "invalid key", "permission")):
        return "config_error"
    if any(token in s for token in ("rate limit", "429", "quota", "too many requests", "server error", "content policy", "moderation")):
        return "model_error"
    if re.search(r"\b5\d\d\b", s):
        return "model_error"
    if any(token in s for token in ("timeout", "timed out", "network", "econn", "fetch", "sse", "abort", "connection", "dns", "unreachable", "address already in use")):
        return "infra_error"
    return "model_error"


def _fallback_usage(messages: list, response_payload: dict) -> dict:
    prompt_tokens = _rough_token_count(messages)
    completion_tokens = _rough_token_count(response_payload)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated": True,
    }


# === 429 / 限流自动退避 ===============================================
# Agent 每个 step 都要调一次 LLM,免费层配额很容易被乘数效应打爆。
# 这里只针对"每分钟限流(RPM)"做有限次退避重试:
#   - 服务端给了 retryDelay 就按它睡(封顶,避免一次卡死几十秒)
#   - 没给就指数退避 (2s, 4s, ...)
#   - 若服务端要求等的时间超过封顶,多半是"每日配额"耗尽,重试无意义 → 直接抛出
_RETRY_MAX_ATTEMPTS = 3      # 总尝试次数(含首次)
_RETRY_MAX_SLEEP = 20.0      # 单次退避最长睡多久(秒)
_RETRY_DELAY_RE = re.compile(r"retry[_-]?delay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def _is_rate_limit_error(e: Exception) -> bool:
    """识别 429 / 限流类错误(兼容 openai SDK 与各家兼容端点的文案)。"""
    if getattr(e, "status_code", None) == 429:
        return True
    s = str(e).lower()
    return any(t in s for t in ("429", "resource_exhausted", "rate limit", "quota", "too many requests"))


def _retry_delay_for(e: Exception, attempt: int) -> Optional[float]:
    """算出本次该睡几秒;返回 None 表示"不该重试"(等待过久/每日配额)。"""
    m = _RETRY_DELAY_RE.search(str(e))
    if m:
        delay = float(m.group(1))
        if delay > _RETRY_MAX_SLEEP:
            return None  # 服务端要求等太久,多半是每日配额耗尽,重试也是 429
        return delay + 0.5
    return min(2.0 ** attempt, _RETRY_MAX_SLEEP)  # 没给 retryDelay → 指数退避


def _llm_call(messages: list, tools_schema: list, provider: str, model_override: str) -> dict:
    """
    调一次 LLM 并返回结构化结果。

    注意:只有启用了工具时才传 tools 参数。因为:
      1. 空的 tools=[] 某些模型会报错
      2. 不传等于告诉模型"就纯聊天",行为更稳定

    遇到 429/限流时按 retryDelay 做有限次退避重试,见上方常量。
    """
    client, model = _get_client_and_model(provider, model_override)
    kwargs = {"model": model, "messages": messages}
    if tools_schema:
        kwargs["tools"] = tools_schema
        kwargs["tool_choice"] = "auto"

    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        t0 = time.time()
        try:
            resp = client.chat.completions.create(**kwargs)
            break
        except Exception as e:
            delay = _retry_delay_for(e, attempt) if _is_rate_limit_error(e) else None
            if delay is None or attempt == _RETRY_MAX_ATTEMPTS:
                raise  # 非限流错误 / 重试无意义 / 已用尽次数 → 交给上层转成 error 事件
            time.sleep(delay)

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
        "model": model,
        "provider": provider or _DEFAULT_PROVIDER,
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
            {"tool": name, "status": "arg_parse_error", "code": "arg_parse_error", "raw_args": raw_args},
            f"参数解析失败:{e}。原始参数:{raw_args}",
        )

    # 边界 2: 未知工具
    impl = get_tool_impl(name)
    if impl is None and custom_tools_by_name and name in custom_tools_by_name:
        result = _render_custom_tool_result(custom_tools_by_name[name], args)
        if len(result) > 3000:
            result = result[:3000] + "\n...(mock 结果被截断)"
        return (
            {"tool": name, "args": args, "status": "mock_ok", "code": "mock_ok", "source": "custom"},
            result,
        )

    if impl is None:
        return (
            {"tool": name, "args": args, "status": "unknown_tool", "code": "unknown_tool"},
            f"未知工具 {name}",
        )

    # 边界 3a: 工具层主动拒绝(代码级沙箱拦下越权请求)
    # 这是结构化信号,前端无需正则匹配中文文案即可识别"安全边界生效"。
    try:
        result = impl(**args)
    except PolicyViolation as e:
        return (
            {"tool": name, "args": args, "status": "policy_violation", "code": "policy_violation", "reason": str(e)},
            f"已被代码级沙箱拦截:{e}",
        )
    # 边界 3b: 工具执行异常(工具本身的 bug,不是策略拦截)
    except Exception as e:
        return (
            {"tool": name, "args": args, "status": "exec_error", "code": "exec_error", "error": str(e)},
            f"工具执行异常:{e}",
        )

    # 截断过长结果,防止单次工具调用就吃掉大半 context
    if len(result) > 3000:
        result = result[:3000] + "\n...(结果被截断)"

    return (
        {"tool": name, "args": args, "status": "ok", "code": "ok", "source": "built_in"},
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
    provider: str = None,
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

    for step in range(start_step, max_steps + 1):
        try:
            # _llm_call 用的是同步 OpenAI 客户端,直接调用会阻塞整个事件循环
            # (SSE 推流、/api/health 轮询全卡住)。丢到线程池里跑,让循环继续转。
            resp = await asyncio.to_thread(
                _llm_call, messages, tools_schema, provider, model_override
            )
        except Exception as e:
            yield AgentEvent(
                event="error",
                step=step,
                data={"error": str(e), "code": _classify_error_code(e)},
            )
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
                "model": resp["model"],
                "provider": resp["provider"],
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
        step=max_steps,
        data={
            "max_steps": max_steps,
            "messages_snapshot": messages,
            "hint": "Agent 超过最大步数仍未给出回答,可能陷入循环。考虑调整 prompt 或增大 max_steps。",
        },
    )


def _build_memory_message(memory: List[str]) -> Optional[dict]:
    """
    把前端传来的"已记住的事实"列表拼成一条独立的 role:system 消息。

    刻意不把它拼进 system_prompt 字符串,而是单独成一条 system 消息,原因是教学:
    在 messages 列表里能清清楚楚看到"记忆"就是 messages[1] 这一行,
    和 system prompt(messages[0])、用户输入分得开。这正是 L6 要让人看见的——
    长期记忆的"读"端,不过是会话开头多 append 了一条 system 消息而已。

    返回 None 表示没有可注入的记忆(列表为空或全是空白)。
    """
    facts = [f.strip() for f in (memory or []) if f and f.strip()]
    if not facts:
        return None
    lines = "\n".join(f"- {f}" for f in facts)
    content = (
        "以下是关于用户的长期记忆(来自过去的会话,跨会话保留)。"
        "请在本次对话中把它们当作已知事实,无需用户重复说明:\n"
        f"{lines}"
    )
    return {"role": "system", "content": content}


async def run_agent(
    user_input: str,
    system_prompt: str,
    enabled_tools: List[str],
    max_steps: int,
    history: List[dict],
    memory: List[str] = None,
    provider: str = None,
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
    #
    # 长期记忆只在"新会话开头"注入一次,作为 system_prompt 之后的第二条 system 消息。
    # 一旦注入,它就进了 messages,之后随 history 滚动一直带着——和 Claude Code 的
    # CLAUDE.md 同构:会话中途改记忆不影响当前会话。这是 L6 的核心对照点。
    if not history:
        messages = [{"role": "system", "content": system_prompt}]
        memory_message = _build_memory_message(memory)
        if memory_message is not None:
            messages.append(memory_message)
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
        provider=provider,
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
    provider: str = None,
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
        provider=provider,
        model_override=model_override,
        custom_tools=custom_tools,
        manual_tools=manual_tools,
        start_step=current_step + 1,
    ):
        yield ev
