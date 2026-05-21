"""
lessons.py —— 关卡课程定义

每个关卡 = 任务说明 + 锁定的配置 + 预设值 + Aha + 解读浮层。
前端按 locked_config 禁用/隐藏控件，按 preset_config 灌默认值。

设计原则:
  1. 关卡的核心交付物是"看到一个现象"，不是"通过一个测试"
  2. 全部自评式：用户点 "I see it" 推进，系统不做自动判定
  3. 关卡定义和代码同源版本控制，方便迭代

后续 Lesson 3-5 会在后续里补齐。
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
            "max_steps_visible": False,
            "system_prompt_editable": False,
        },

        # 进入关卡时灌进前端的默认值
        "preset_config": {
            "system_prompt": "你是一个简洁的助手。直接回答用户的问题，不要过多解释。",
            "enabled_tools": [],
            "custom_tools": [],
            "manual_tools": [],
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
    {
        "id": "lesson2",
        "order": 2,
        "title": "那只手其实是你的",
        "subtitle": "看见 LLM 不会真的'调用'工具",
        "estimated_minutes": 7,

        "locked_config": {
            "enabled_tools": ["get_current_time"],
            "tool_panel_visible": True,
            "custom_tools_visible": False,
            "max_steps_visible": False,
            "system_prompt_editable": False,
        },

        "preset_config": {
            "system_prompt": (
                "你是一个助手。当用户问到当前时间、日期等需要外部信息的问题时，"
                "请使用提供的工具获取，不要凭空猜。"
            ),
            "enabled_tools": ["get_current_time"],
            "custom_tools": [],
            "manual_tools": [],
            "max_steps": 5,
        },

        "task_intro": (
            "上一关你看到了「记忆」是宿主在 append 列表。这一关看一个更激进的事实：**LLM 也不会真的'调用'工具**。"
            "它只会吐一段 JSON 说「请帮我叫 X 函数」，真正动手的是 agent loop 那段 Python。"
            "如果让你自己来当那只手，模型分不出区别。"
        ),

        "task_steps": [
            {
                "instruction": "在输入框输入：**现在几点？**",
                "hint": (
                    "模型不会算时间，必须借助工具。看右栏 RUN INSPECTOR 时间轴："
                    "先冒出一条 `llm_response`（content 为空，只有 tool_calls）→ `tool_call` → `tool_result` → 第二条 `llm_response` 才是给你的回答。"
                ),
            },
            {
                "instruction": "把 RUN INSPECTOR 切到 **Messages** 视图，找最后那条 `role: tool` 的消息。",
                "hint": (
                    "那条消息就是 Python 真的跑了 `datetime.now()` 之后写进 messages 列表的——"
                    "模型自己一字未动，它只是看到列表里多了一行 observation。"
                ),
            },
            {
                "instruction": "点中栏顶部的 **🗑 清空会话**。",
                "hint": "同样的干净状态，下面我们换个玩法：让你来当那只手。",
            },
            {
                "instruction": (
                    "在左栏工具面板找到 `get_current_time`，"
                    "点它旁边的 **🤖 真实** 按钮，把它切到 **✋ 人工** 模式。"
                ),
                "hint": "✋ 人工 = agent 不会真去跑这个工具，而是停下来等你填 observation。",
            },
            {
                "instruction": "再次输入：**现在几点？**",
                "hint": (
                    "这次时间轴会出现一个青色的 `等待人工返回` 块，中栏会弹出一个输入框——agent 暂停了，把控制权交还给你。"
                ),
            },
            {
                "instruction": (
                    "在那个输入框里随便填一个**明显假的时间**，比如 `2099-01-01 00:00:00`，提交。"
                ),
                "hint": (
                    "模型会一本正经地把这个时间转告用户。它没法分辨这条 observation 是 Python 跑出来的、还是你手敲的——"
                    "对它而言，两者都是 messages 列表里一条 `role: tool`。"
                ),
            },
        ],

        "aha": (
            "两条 `role: tool` 的消息在 messages 列表里长得一模一样：一条是 Python 写的，一条是你手敲的。"
            "模型对这两者无法区分——**谁在往 messages 里 append observation，谁就定义了模型眼中的'现实'**。"
        ),

        "explanation_md": (
            "## 模型并没有'调用'工具\n\n"
            "每次 `llm_response` 里的 `tool_calls` 字段，本质上就是模型吐出的一段 JSON："
            "「我想叫 `get_current_time`，参数是 `{}`」。它**没有**任何执行能力——"
            "执行的是 agent loop 那 80 行 Python（看 `backend/agent.py:_exec_tool_call`）。\n\n"
            "**完整的一轮循环**：\n\n"
            "1. 模型吐 `tool_calls`（一段意图，仅此而已）\n"
            "2. agent loop 调对应的 Python 函数；本关把它切成「人工」就是把这一步换成了你\n"
            "3. agent loop 把结果包成 `{role: 'tool', tool_call_id: ..., content: ...}` 塞进 messages\n"
            "4. 再调一次模型——模型基于新的 messages 给最终回答\n\n"
            "**三个推论**：\n\n"
            "1. **模型没有「动手」能力**——能动的是宿主程序。给模型加「工具」= 你写一个 Python 函数 + 注册它的 schema\n"
            "2. **错误也是 observation**——工具抛异常时，把错误信息当字符串塞回 messages 就行，不要 raise 出去\n"
            "3. **谁定义 observation，谁定义现实**——所以 prompt injection 真正的攻击面是工具结果，不是用户输入\n\n"
            "*「agent = LLM + 一堆工具」是误解。准确说法是：agent = 你写的一段循环，"
            "每一步喂给 LLM 一个不断生长的 messages 列表，并按 LLM 的指示去操纵世界。*"
        ),

        "next_hint": "下一关：一道题分两步——看 agent 怎么把任务拆开。",
    },
]


def get_lesson(lesson_id: str) -> Optional[Dict[str, Any]]:
    for lesson in LESSONS:
        if lesson["id"] == lesson_id:
            return lesson
    return None
