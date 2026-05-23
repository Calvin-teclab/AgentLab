"""
lessons.py —— 关卡课程定义

每个关卡 = 任务说明 + 锁定的配置 + 预设值 + Aha + 解读浮层。
前端按 locked_config 禁用/隐藏控件，按 preset_config 灌默认值。

设计原则:
  1. 关卡的核心交付物是"看到一个现象"，不是"通过一个测试"
  2. 全部自评式：用户点 "I see it" 推进，系统不做自动判定
  3. 关卡定义和代码同源版本控制，方便迭代

五关全在,作为 agent 第一性原理课闭环。Lesson 1-4 讲机制(它是什么),
Lesson 5 讲落地(你怎么塑造它)。
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
    {
        "id": "lesson3",
        "order": 3,
        "title": "它没在「规划」",
        "subtitle": "所谓「多步任务」其实是 loop 一次问一句",
        "estimated_minutes": 8,

        "locked_config": {
            "enabled_tools": ["list_dir", "read_file", "calculator"],
            "tool_panel_visible": True,
            "custom_tools_visible": False,
            # 本关刻意让 max_steps 可见可改——后半段要让学生亲手把它调成 2 看效果
            "max_steps_visible": True,
            "system_prompt_editable": False,
        },

        "preset_config": {
            "system_prompt": (
                "你是一个谨慎的助手。\n\n"
                "工作原则:\n"
                "1. 不确定环境时,先用 list_dir 之类的探测工具。\n"
                "2. 数字计算必须用 calculator,不要心算。\n"
                "3. 一次只做一件事,看到工具返回的内容再决定下一步。"
            ),
            "enabled_tools": ["list_dir", "read_file", "calculator"],
            "custom_tools": [],
            "manual_tools": [],
            "max_steps": 10,
        },

        "task_intro": (
            "前两关你看到了模型没有记忆、也不会真的'调用'工具。这一关再砸一个反直觉的事实:**它也不会'规划'**。"
            "我们常说 agent '把任务拆成几步',其实是 agent loop 在反复问模型『下一步要做什么』——"
            "模型每次只决定一个动作,看到结果后再被问一次。所谓'规划'是外面的循环在替它干。"
        ),

        "task_steps": [
            {
                "instruction": "在输入框输入:**算一下 scores.txt 里所有人的平均分**",
                "hint": (
                    "等它跑完,大约 4 个 Step:list_dir → read_file → calculator → 最终回答。"
                    "右栏 RUN INSPECTOR 时间轴会一段一段冒出来,中栏顶部的 LLM Steps 进度条会同步亮起 4 格。"
                ),
            },
            {
                "instruction": "把 RUN INSPECTOR 切到 **Messages** 视图,数一下 `role: assistant` 的消息有几条。",
                "hint": (
                    "应该有 4 条 assistant 消息。前 3 条 content 都是空字符串——它们不是回答你,只是模型在吐 tool_calls。"
                    "第 4 条才有 content,是给你的最终自然语言答案。"
                ),
            },
            {
                "instruction": (
                    "对照看 **第 1 条** assistant 的 tool_calls 和 **第 3 条** assistant 的 tool_calls。"
                    "第 1 条调的是 list_dir(几乎没参数), 第 3 条 calculator 调用的表达式里带着具体数字(像 90+85+78+92+68)。"
                ),
                "hint": (
                    "关键问题:**第 3 条 assistant 是怎么知道这些数字的?** 它发言的时候,这些数字早已经在 messages 列表里——"
                    "是第 2 条 `role: tool` (read_file 的返回结果)告诉它的。\n\n"
                    "**模型第 1 次发言时根本不知道这些数字。** 它只是先扔个 list_dir 探探路,等到第 3 次发言它已经'读到'了文件内容,才有依据写出那个算式。"
                ),
            },
            {
                "instruction": (
                    "现在做对照实验:**把左栏 MAX_STEPS 滑到 2**,点中栏 **🗑 清空会话**,重新输入同一句:"
                    "**算一下 scores.txt 里所有人的平均分**。"
                ),
                "hint": (
                    "这次 agent 会撞 max_steps:模型还没机会走到 calculator 那一步,循环就被强制中止了。"
                    "时间轴最后一条会是红色的 `max_steps` 事件。同一个模型、同一个 prompt——只是循环跑不够步数,它就'不会做'了。"
                ),
            },
            {
                "instruction": "把 MAX_STEPS 滑回 10,再清空会话发一次,确认它又'会做'了。",
                "hint": "对照很干净:能力变了一倍,只因外面允许它多说几次话。",
            },
        ],

        "aha": (
            "MAX_STEPS=10 时模型'会规划'多步任务,=2 时它'不会'——同一个模型,同一个 prompt。"
            "**这说明所谓'规划能力'根本不在模型里,而在外部循环允许它走多少步。** "
            "每多一步,模型就多看一行 observation,多一次发言机会;所谓'拆任务',从来都是 loop 在帮它一次问一句。"
        ),

        "explanation_md": (
            "## 「规划」是循环,不是模型\n\n"
            "ReAct loop 的真实形态(看 `backend/agent.py:_run_agent_loop`):\n\n"
            "1. **Reason**: 把当前 messages 喂给 LLM,LLM 回一段「思考 + tool_calls」或「最终回答」\n"
            "2. **Act**: 如果有 tool_calls,host 跑工具\n"
            "3. **Observe**: host 把 tool result 追加到 messages\n"
            "4. **回到 Reason**——再调一次 LLM(注意:**messages 已经多了一行**)\n\n"
            "模型在每一次发言里看到的世界是**单调增长**的:它无法'退回'去重做之前的决定,但每多走一步就多一行信息。"
            "所谓'规划',就是这个循环跑得够久。\n\n"
            "**三个推论**:\n\n"
            "1. **模型没有'整体规划'** —— 它每一次发言都是基于当前 messages 列表做局部决定。所谓 agent '把任务拆开了',是 loop 在帮它一次问一句\n"
            "2. **MAX_STEPS 是真正的能力上限** —— prompt 写得再花,循环不跑够步数,它走不到答案。这就是为什么所有 agent 框架都要管 step budget\n"
            "3. **错误恢复也是同一机制** —— 工具失败 → host 把错误塞进 messages → 下一次 LLM 发言时'看到'失败,自己决定改路径。模型没有 try-catch,只有'下一次能看到更多'\n\n"
            "*前三关合起来就是 agent 的第一性原理:无状态的 LLM + 宿主管理的 messages + 外部循环跑够多步。后面的所有工程问题——工具描述、记忆压缩、并行调用、安全边界——都建立在这三条之上。*"
        ),

        "next_hint": "下一关:同一个工具改一段 description, 同一个模型从'不调'变成'调对'。",
    },
    {
        "id": "lesson4",
        "order": 4,
        "title": "Description 是模型的眼睛",
        "subtitle": "模型看不见工具的代码,它看见的只有那段说明文字",
        "estimated_minutes": 10,

        "locked_config": {
            "enabled_tools": ["consult_weather"],
            "tool_panel_visible": True,
            # 这一关核心动作就是编辑 mock 工具的 description
            "custom_tools_visible": True,
            "max_steps_visible": False,
            "system_prompt_editable": False,
        },

        "preset_config": {
            "system_prompt": (
                "你是一个生活助手,可以使用提供的工具帮用户解决问题。"
                "需要外部信息(比如天气、时间、地点)时主动调用工具,不要凭空编。"
            ),
            "enabled_tools": ["consult_weather"],
            "custom_tools": [
                {
                    "name": "consult_weather",
                    # 故意写糟糕:含糊 + 英文 + 没说"什么场景下应该调"
                    "description": "weather tool",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string", "description": "city"},
                        },
                        "required": ["city"],
                    },
                    "response_template": (
                        "[mock] {{arg.city}} 明天天气预报:\n"
                        "天气: 雷阵雨\n"
                        "温度: 18-24°C\n"
                        "降水概率: 80%\n"
                        "建议: 带伞,加件外套"
                    ),
                },
            ],
            "manual_tools": [],
            "max_steps": 5,
        },

        "task_intro": (
            "前三关你看到了模型没记忆、不调用工具、不规划。这一关再揭一层:"
            "**模型决定要不要调一个工具,看的只是 description 那一段字符串。** "
            "工具的 Python 实现写得再准、返回再可靠,description 写得不到位,模型就视而不见。"
        ),

        "task_steps": [
            {
                "instruction": "在输入框输入:**明天北京要带伞吗?**",
                "hint": (
                    "左栏已经挂了一个 mock 工具 `consult_weather`——按说能直接回答这种问题。"
                    "但你看时间轴大概率会发现:**模型没调它**,或者调了但参数古怪,"
                    "也可能干脆泛泛地说'你自己看天气预报吧'。\n\n"
                    "(如果它这次碰巧调对了,多试几次或者换个问法,你会发现行为很不稳定。)"
                ),
            },
            {
                "instruction": "切到左栏 **Tools** tab,找到 `consult_weather` 卡片,点 **编辑** 按钮。",
                "hint": (
                    "编辑面板里看 **Description** 字段——就两个英文词:`weather tool`。"
                    "**这就是模型决定'要不要调它'的全部依据。** "
                    "工具的实现代码、返回模板、参数 schema 都对,但 description 不告诉模型'什么场景下用我',它就只能猜。"
                ),
            },
            {
                "instruction": (
                    "把 Description 改成这一段:\n\n"
                    "**获取指定城市的明天天气预报。适用场景:用户询问明天天气、温度、是否需要带伞、要不要穿厚衣服、出行天气建议。不适用:历史天气查询、其它日期天气、非中国大陆城市。**\n\n"
                    "同时把 city 参数的 description 改成:**城市中文名,例如 北京 / 上海 / 杭州**。\n\n"
                    "改完点「保存工具」。"
                ),
                "hint": (
                    "三个关键改进:\n"
                    "1. **场景具体**:直接告诉模型「问天气 / 温度 / 伞 / 衣服 / 出行」时调这个工具\n"
                    "2. **「适用 / 不适用」对照**:模型默认倾向于'多调几个看看',显式说不该调的场景能压住乱调\n"
                    "3. **写中文 + 具体例子**:中文用户问中文问题时,中文 description 匹配率高得多"
                ),
            },
            {
                "instruction": "点中栏 **🗑 清空会话**,再次输入完全一样的问题:**明天北京要带伞吗?**",
                "hint": (
                    "这次时间轴里应该清晰地冒出 `tool_call: consult_weather(city='北京')` → `tool_result` → 最终回答。"
                    "**同一个模型,同一段 system prompt,同一个用户问题。** 唯一改变的是 description 那段字符串。"
                ),
            },
            {
                "instruction": (
                    "好奇心驱动:再试两个边界问题,看 description 的「不适用」段是否真起作用:\n"
                    "1. 「我穿短袖出门冷不冷?」(温度类,适用,应该会调)\n"
                    "2. 「去年北京冬天最低多少度?」(历史天气,不适用,应该会拒)"
                ),
                "hint": (
                    "好的 description 不是让模型'啥都调',是让它**判断对的时机才调**。"
                    "「不适用」那一段往往比「适用」更难写,但用对了,模型就不会拿一把锤子见啥都敲。"
                ),
            },
        ],

        "aha": (
            "Description 写法 = 模型对这个工具的全部认知。"
            "「weather tool」它就不知道该不该调;写清「适用 / 不适用」场景,它就调对。"
            "**这不是 prompt engineering 的玄学,这是模型只能看见 description 这一段字符串这个事实。**"
        ),

        "explanation_md": (
            "## Description 决定一切\n\n"
            "在 `_llm_call` 这一步,我们把每个工具的 schema 拼成 JSON 喂给模型,大致长这样:\n\n"
            "```json\n"
            "{\n"
            '  \"type\": \"function\",\n'
            '  \"function\": {\n'
            '    \"name\": \"consult_weather\",\n'
            '    \"description\": \"weather tool\",\n'
            '    \"parameters\": {\"type\": \"object\", \"properties\": {...}}\n'
            "  }\n"
            "}\n"
            "```\n\n"
            "**模型看见的工具世界就这点东西**:一个 name + 一段 description + 一份 parameters JSON Schema。"
            "Python 实现长什么样、response 怎么生成、调用成本多高、有没有副作用——它都不知道。"
            "它决定「要不要调这个工具」的全部依据,就是这段 description。\n\n"
            "**三个推论**:\n\n"
            "1. **写 description = 在跟模型谈判** —— 你在告诉它「这种场景请用我,那种场景请别用」。description 越具体,模型越听话\n"
            "2. **「不适用」比「适用」更重要** —— 模型默认倾向于「调点工具显得有动作」。如果你不显式说什么时候**不**该调,它容易乱调或调错时机\n"
            "3. **参数 schema 也是 description 的一部分** —— `parameters.properties.X.description` 决定模型怎么填那个字段。"
            "字段描述写「string」和写「订单号,例如 OD-2026-001」,效果差几个数量级\n\n"
            "**工程实务**:每次发现 agent「应调未调」或「误调工具」,先检查 description,**不要急着改 system_prompt**——"
            "前者是这个工具的「合同」,作用域局部;后者是全局的语气和原则,改一处影响所有工具。"
            "改 description 是手术刀,改 prompt 是大喇叭。"
        ),

        "next_hint": "下一关:你已经能写好工具了——下一关看 system prompt 怎么左右 agent 的'性格',同一套工具如何呈现完全不同的行为风格。",
    },
    {
        "id": "lesson5",
        "order": 5,
        "title": "System prompt 是 agent 的人格",
        "subtitle": "同一套工具同一个模型,不同 prompt = 完全不同的产品",
        "estimated_minutes": 10,

        "locked_config": {
            "enabled_tools": ["read_file", "calculator", "write_file"],
            "tool_panel_visible": True,
            "custom_tools_visible": False,
            "max_steps_visible": False,
            # 本关核心动作就是切 prompt,必须可编辑
            "system_prompt_editable": True,
        },

        "preset_config": {
            # 与 frontend systemPromptPresets[默认] 同步——本关学生会反复在三档间切换
            "system_prompt": (
                "你是一个助手，可以使用提供的工具完成任务。\n\n"
                "工作原则：\n"
                "1. 先规划，再行动。复杂任务分步执行。\n"
                "2. 不确定环境时，先用 list_dir 之类的\"探测\"工具。\n"
                "3. 数字计算必须用 calculator，不要心算。\n"
                "4. 工具返回错误时，分析原因后再尝试，不要重复犯同样的错。"
            ),
            "enabled_tools": ["read_file", "calculator", "write_file"],
            "custom_tools": [],
            "manual_tools": [],
            "max_steps": 10,
        },

        "task_intro": (
            "前 4 关讲完了 agent loop 的'物理学':没记忆、不真调工具、不真规划、description 决定眼界。"
            "**这一关讲落地**:同一套工具、同一个模型、同一个问题,仅仅换一段 system prompt,"
            "会变成三个完全不同的 agent 产品。"
        ),

        "task_steps": [
            {
                "instruction": (
                    "确认左栏 System Prompt 已经是「默认」型(顶部三个 preset 按钮里第一个是高亮的——如果不是,点一下「默认」)。"
                    "然后在输入框输入:**把 scores.txt 里的统计(总分、平均、最高最低)写入 report.txt**"
                ),
                "hint": (
                    "等它跑完,大约 4-6 个 Step。**记一下这次的特征**:\n"
                    "1. 它每一步前说了什么 / 没说什么\n"
                    "2. 最终的自然语言回答有多长\n"
                    "3. 走的工具顺序\n\n"
                    "下面两次跑会跟这次做对比,所以这次要先看清「基线」长啥样。"
                ),
            },
            {
                "instruction": (
                    "切到左栏 System Prompt 面板上方的 **「谨慎型」** preset 按钮,点一下。"
                    "下面的 prompt 文本框会变成另一段说明——读一下,看它跟「默认」型差在哪。"
                ),
                "hint": (
                    "差异关键词:**「每一步完成后向用户解释」「写入前先告知内容」「保守方案」「详细解释」**。"
                    "这一段告诉模型:别闷头干,先报告再动作。"
                ),
            },
            {
                "instruction": (
                    "点中栏 **🗑 清空会话**,再次输入**完全一样的问题**:"
                    "**把 scores.txt 里的统计(总分、平均、最高最低)写入 report.txt**"
                ),
                "hint": (
                    "看右栏时间轴 + 中栏对话框,跟刚才「默认」型那次比:\n"
                    "1. 这次很可能在动手前先用自然语言解释要做什么\n"
                    "2. 写入 report.txt 之前会预告内容(甚至想征求同意)\n"
                    "3. 每个工具结果会有一段详细解读\n"
                    "4. final answer 篇幅明显变长\n\n"
                    "**同一个模型,同一份工具,同一个用户问题。** 唯一变了的是 system prompt 那段字符串。"
                ),
            },
            {
                "instruction": (
                    "切到 **「高效型」** preset,清空会话,第三次发同样的问题:"
                    "**把 scores.txt 里的统计(总分、平均、最高最低)写入 report.txt**"
                ),
                "hint": (
                    "「高效型」的 prompt 大致是「直接行动,减少解释,结果简洁」。"
                    "这次大概率会看到:\n"
                    "1. 工具一个接一个跑,中间几乎没有自然语言铺垫\n"
                    "2. final answer 极短(可能就两行:平均分 X,已写入)\n"
                    "3. 整个过程 token 用量明显比「谨慎型」少\n\n"
                    "**三次跑放一起对比**,你应该看到三种「性格」差异——但 backend 代码、工具、模型、查询全没动。"
                ),
            },
            {
                "instruction": (
                    "回到中栏,翻三次跑的对话历史,把每次的 final answer 篇幅 + 工具调用解释多寡 + 是否预告写入 在脑子里过一遍。"
                    "试试自己写一段更极端的 system prompt——比如「你是一个安全审计员,每次写入前必须列出'修改前 / 修改后'对照,并标记影响范围」——再发一次同样的问题。"
                ),
                "hint": (
                    "你写什么调子,它就活成什么调子。这就是 agent 产品差异化的底层机制——"
                    "OpenAI / Anthropic / 火山 同一个模型,被几百个产品包装成几百种 agent,差异 90% 来自 system prompt。"
                ),
            },
        ],

        "aha": (
            "三次跑的 backend 代码、工具栈、模型权重、用户问题全部一样,唯一变量是 system prompt——"
            "结果却像三个不同产品。这说明 **agent 的'性格' / '风格' / '调性'根本不是某种模型能力,"
            "它就是 system prompt 这一字符串。你写什么调子,它就活成什么调子。**"
        ),

        "explanation_md": (
            "## System prompt 在循环里干了什么\n\n"
            "回到第一关学到的事实:模型每次发言之前看到的全部世界,就是 messages 列表。"
            "**system prompt 是这个列表的第 0 条,role 是 `system`**——每一轮 LLM 调用都会把它一字不漏地重新喂给模型。\n\n"
            "```python\n"
            "messages = [\n"
            "    {\"role\": \"system\", \"content\": \"<你的 system prompt>\"},  # 每次都在,模型每次都看\n"
            "    {\"role\": \"user\", \"content\": \"...\"},\n"
            "    {\"role\": \"assistant\", \"tool_calls\": [...]},\n"
            "    {\"role\": \"tool\", \"content\": \"...\"},\n"
            "    ... # loop 跑多久,后面就有多长\n"
            "]\n"
            "```\n\n"
            "模型被训练时见过海量「优先服从 role=system 的指令」的样本,所以这一条的指令权重最高——"
            "它会贯穿后续所有 LLM 调用,左右每一步的决定:要不要调工具、调哪个、怎么解释、final answer 怎么写。\n\n"
            "**三个推论**:\n\n"
            "1. **「agent = LLM + 工具」是不完整的等式** —— 准确说法是 **`agent = LLM + 工具 + 一段定调子的 system prompt`**。"
            "前一个你不掌控,后两个完全是你写的\n"
            "2. **同一份后端代码 + 同一份模型 → 任意多个 agent 产品** —— 这就是为什么 ChatGPT / Claude / Doubao 同一个模型能被几百个 SaaS 包装成几百种产品。"
            "你看到的「不同 AI 助手」,后端差异 90% 是 system prompt 的差异\n"
            "3. **改 system prompt = 全局副作用,改 description = 局部修补** —— 上一关说改 description 是手术刀,改 prompt 是大喇叭。"
            "「agent 整体太乱」找 prompt,「某个工具调不对」找 description\n\n"
            "**这一关之后,前五关合起来就是 agent 工程的全部基本盘**:\n"
            "- L1 你掌控 messages 列表(没记忆 = 你 append)\n"
            "- L2 你掌控工具执行(host 才是动手的)\n"
            "- L3 你掌控循环步数(规划 = loop 跑够)\n"
            "- L4 你掌控工具描述(description 决定调不调)\n"
            "- L5 你掌控 agent 调性(system prompt 是它的人格)\n\n"
            "*所有「agent 工程」都是这五件事的组合艺术。读到这里你已经看懂 agent 不再是黑盒——后面的工程问题(成本控制、长上下文、多 agent、安全审计、可观测性)都是在这五条之上做工程优化。*"
        ),

        "next_hint": (
            "你已经走完了 agent 第一性原理的五关。点上方「自由模式」就是 playground 完整开放——"
            "工具实验室、Eval benchmark、Mass scenario templates 都在那边,把你刚学到的拿去捏一个属于你自己的 agent。"
        ),
    },
]


def get_lesson(lesson_id: str) -> Optional[Dict[str, Any]]:
    for lesson in LESSONS:
        if lesson["id"] == lesson_id:
            return lesson
    return None
