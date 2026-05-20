"""
main.py —— FastAPI 入口

两个路由:
  GET  /api/tools          返回工具注册表(前端渲染复选框)
  POST /api/run            SSE 流式执行 agent,实时把每步事件推给前端

关于 SSE(Server-Sent Events):
  - 这是一种单向的服务器到客户端流式协议
  - 浏览器原生 EventSource API 直接消费,不需要 WebSocket
  - 比 WebSocket 简单得多,天然适合"服务器持续推事件"的场景
  - 正是 ChatGPT/Claude 等产品打字机效果的底层实现
"""
from __future__ import annotations

import json

from dotenv import load_dotenv

# 注意:load_dotenv 必须在 import agent 之前,否则 agent.py 的模块级 OpenAI
# 初始化会拿不到 ARK_API_KEY 导致启动失败。
load_dotenv()

from fastapi import FastAPI                                          # noqa: E402
from fastapi.middleware.cors import CORSMiddleware                   # noqa: E402
from sse_starlette.sse import EventSourceResponse                    # noqa: E402

from agent import continue_agent_after_tool, run_agent                # noqa: E402
from evals import BENCHMARK_CASES, FAILURE_TAXONOMY, MASS_TEMPLATES   # noqa: E402
from lessons import LESSONS                                          # noqa: E402
from schemas import ContinueToolRequest, RunAgentRequest              # noqa: E402
from tools import TOOL_REGISTRY                                      # noqa: E402


app = FastAPI(title="Agent Playground", version="0.1.0")

# 允许前端跨域访问(前端可能直接 file:// 或 localhost:5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/tools")
def list_tools():
    """返回所有可用工具的元信息,前端据此渲染复选框。"""
    return {
        name: {
            "name": name,
            "description": entry["schema"]["function"]["description"],
            "parameters": entry["schema"]["function"].get("parameters", {}),
        }
        for name, entry in TOOL_REGISTRY.items()
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/lessons")
def list_lessons():
    """返回关卡清单。前端按 order 排序渲染选择器。"""
    return {"lessons": LESSONS}


@app.get("/api/eval-assets")
def eval_assets():
    """返回评估用例、业务模板和失败归因 taxonomy。"""
    return {
        "benchmarks": BENCHMARK_CASES,
        "mass_templates": MASS_TEMPLATES,
        "failure_taxonomy": FAILURE_TAXONOMY,
    }


@app.post("/api/run")
async def run(req: RunAgentRequest):
    """
    以 SSE 流式返回 agent 执行过程。

    前端用 fetch + ReadableStream 消费(而不是 EventSource),
    因为 EventSource 不支持 POST。我们自己解析 text/event-stream 格式即可。
    """

    async def event_stream():
        try:
            async for ev in run_agent(
                user_input=req.user_input,
                system_prompt=req.system_prompt,
                enabled_tools=req.enabled_tools,
                max_steps=req.max_steps,
                history=req.history,
                model_override=req.model_override,
                custom_tools=req.custom_tools,
                manual_tools=req.manual_tools,
            ):
                # sse_starlette 约定: yield 一个 dict,event 字段是 SSE 的 event name
                yield {
                    "event": ev.event,
                    "data": json.dumps(
                        {
                            "event": ev.event,
                            "step": ev.step,
                            "data": ev.data,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                }
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"event": "error", "data": {"error": str(e)}}),
            }

    return EventSourceResponse(event_stream())


@app.post("/api/continue")
async def continue_after_tool(req: ContinueToolRequest):
    """
    人工提供工具返回结果后继续执行 agent。

    这让前端可以暂停在 tool_call,让用户修改 observation,再观察模型如何响应。
    """

    async def event_stream():
        try:
            async for ev in continue_agent_after_tool(
                tool_call_id=req.tool_call_id,
                tool_result=req.tool_result,
                enabled_tools=req.enabled_tools,
                max_steps=req.max_steps,
                history=req.history,
                model_override=req.model_override,
                custom_tools=req.custom_tools,
                manual_tools=req.manual_tools,
            ):
                yield {
                    "event": ev.event,
                    "data": json.dumps(
                        {
                            "event": ev.event,
                            "step": ev.step,
                            "data": ev.data,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                }
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"event": "error", "data": {"error": str(e)}}),
            }

    return EventSourceResponse(event_stream())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
