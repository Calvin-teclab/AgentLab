"""
schemas.py —— API 请求/响应数据模型

单独抽出来是为了:
  1. 前后端字段契约清晰(前端 TS 类型可以照抄)
  2. FastAPI 自动生成 /docs Swagger 文档
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RunAgentRequest(BaseModel):
    """前端发起一次 agent 运行的请求参数"""

    user_input: str = Field(..., description="用户本轮输入")
    system_prompt: str = Field(
        default="你是一个助手,可以使用提供的工具完成任务。",
        description="系统提示词,控制 agent 的行为风格",
    )
    enabled_tools: List[str] = Field(
        default_factory=list,
        description="本次启用的工具名列表,来自 TOOL_REGISTRY 的 keys",
    )
    custom_tools: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "前端定义的教学用 mock 工具。"
            "每个工具包含 name/description/parameters/response_template。"
        ),
    )
    manual_tool_mode: bool = Field(
        default=False,
        description="是否在模型发起工具调用时暂停,由用户手动填写工具返回结果。",
    )
    max_steps: int = Field(default=10, ge=1, le=30, description="循环最大步数")
    # 关键设计:把 messages 历史也带上
    # 让前端完全掌握对话状态,后端无状态。这样:
    #   1. 前端可以随时清空/编辑历史
    #   2. 后端天然支持多用户并发
    #   3. 用户刷新页面不会丢上下文(前端自己可选存 localStorage)
    history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="之前的 messages 历史(不含本轮 user_input)",
    )
    model_override: Optional[str] = Field(
        default=None,
        description=(
            "可选:覆盖后端 .env 中的 ARK_MODEL。"
            "前端教学用,便于切换不同 endpoint。"
            "注意:API Key 永远只在后端,前端无法修改。"
        ),
    )


class ContinueToolRequest(BaseModel):
    """人工填写某个工具调用结果后,让 agent 继续执行。"""

    tool_call_id: str = Field(..., description="待补充 observation 的 tool_call_id")
    tool_result: str = Field(..., description="用户手动填写或修改后的工具返回内容")
    enabled_tools: List[str] = Field(default_factory=list, description="本次启用的工具名列表")
    custom_tools: List[Dict[str, Any]] = Field(default_factory=list, description="前端定义的 mock 工具")
    manual_tool_mode: bool = Field(default=True, description="续跑时是否继续在下一个工具调用处暂停")
    max_steps: int = Field(default=10, ge=1, le=30, description="续跑循环最大步数")
    history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="当前 messages 历史,其中应包含尚未补 observation 的 assistant tool_call",
    )
    model_override: Optional[str] = Field(default=None, description="可选:覆盖后端 .env 中的 ARK_MODEL")


class AgentEvent(BaseModel):
    """SSE 推送给前端的事件(时间轴上每张卡片对应一个事件)"""

    event: str  # user_input / llm_response / tool_call / tool_input_required / tool_result / final_answer / error / max_steps
    step: Optional[int] = None
    data: Dict[str, Any] = Field(default_factory=dict)
