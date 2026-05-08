"""
lessons.py —— 关卡课程定义

每个关卡 = 任务说明 + 锁定的配置 + 预设值 + Aha + 解读浮层。
前端按 locked_config 禁用/隐藏控件，按 preset_config 灌默认值。

设计原则:
  1. 关卡的核心交付物是"看到一个现象"，不是"通过一个测试"
  2. 全部自评式：用户点 "I see it" 推进，系统不做自动判定
  3. 关卡定义和代码同源版本控制，方便迭代

后续 Lesson 2-5 会在 M3、M4 里补齐。
"""
from typing import Any, Dict, List, Optional


LESSONS: List[Dict[str, Any]] = [
    {
        "id": "lesson1",
        "order": 1,
        "title": "记忆是假象",
        "subtitle": "看见 LLM 的无状态本质",
        "estimated_minutes": 5,

        # 锁定字段：true / 数组等代表"锁定为该值且不可改"，*_visible=False 表示隐藏控件
        "locked_config": {
            "enabled_tools": [],
            "tool_panel_visible": False,
            "custom_tools_visible": False,
            "manual_tool_mode": False,
            "manual_tool_mode_visible": False,
            "max_steps_visible": False,
            "system_prompt_editable": False,
        },

        # 进入关卡时灌进前端的默认值
        "preset_config": {
            "system_prompt": "你是一个简洁的助手。直接回答用户的问题，不要过多解释。",
            "enabled_tools": [],
            "custom_tools": [],
            "manual_tool_mode": False,
            "max_steps": 5,
        },

        "task_intro": (
            "亲手验证一个反直觉的事实：LLM **没有记忆**。"
            "它每次回答之前看到的全部世界，就是中栏那个 messages 列表。"
        ),

        "task_steps": [
            {
                "instruction": "在输入框输入：**我叫张三**",
                "hint": "回车发送。看右栏时间轴出现一条 user_input。",
            },
            {
                "instruction": "继续输入：**我叫什么？**",
                "hint": "模型答得出来。看上去它「记得」——其实不是。",
            },
            {
                "instruction": "点中栏顶部的 **🗑 清空会话** 按钮",
                "hint": "中栏 messages 列表会被清空。",
            },
            {
                "instruction": "再次输入：**我叫什么？**",
                "hint": "这一次模型说不知道——因为它本来就什么都不知道。",
            },
        ],

        "aha": (
            "messages 列表清空的瞬间，模型立刻「失忆」。"
            "所谓「对话历史」完全是宿主程序在 append 列表，模型本身一字不存。"
        ),

        "explanation_md": (
            "## 为什么会这样？\n\n"
            "每次调用 `client.chat.completions.create(messages=...)`，"
            "我们都会把整个 messages 列表重新发给模型。"
            "模型的输入是**无状态**的——它只能基于本次调用收到的内容回答。\n\n"
            "**三个推论**：\n\n"
            "1. 「LLM 有记忆」是假象——记忆 = 你在 append 列表\n"
            "2. 让 LLM 「忘掉」某事 = 从列表里 pop 那几条，没有「遗忘 API」\n"
            "3. 让模型「做新事」的唯一方式 = 往列表里塞新内容（用户输入、工具结果、摘要）\n\n"
            "*这是 agent 工程的第一性原理。后续每一关都建立在这一条上。*"
        ),

        "next_hint": "下一关：给模型加一只手——但你会发现，那只手其实是你的。",
    },
]


def get_lesson(lesson_id: str) -> Optional[Dict[str, Any]]:
    for lesson in LESSONS:
        if lesson["id"] == lesson_id:
            return lesson
    return None
