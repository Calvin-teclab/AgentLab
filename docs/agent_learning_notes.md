# 从零手写 Agent：Step 1–4 学习笔记

> 本笔记面向已经跑通 Step 1–4 的学习者，用于复习和快速重建。
> 配套代码：`step1_chat.py` / `step2_manual_tool.py` / `step3_tool_use.py` / `step4_agent.py`
> 模型：DeepSeek-V3（火山方舟），SDK：openai（兼容协议）

---

## 0. 全书一句话

> **Agent = 一个 while 循环 + 一个会"说想用什么工具"的 LLM + 一个负责真正执行工具的宿主程序。**

所有框架、所有论文、所有产品，都是在这句话上做增量。把它刻进肌肉记忆，再看任何东西都不会晕。

---

## 1. 核心世界观：LLM 是无状态的

### 1.1 关键事实

- LLM 唯一能做的事：**读一段文本，猜下一段文本**。
- 它**不会联网、不会跑代码、不会读文件、不会记住上一次对话**。
- 所谓"记忆"、"对话历史"、"工具调用"全是**宿主程序**造出来的假象。

### 1.2 messages 列表 = 模型的全部世界

对话历史就是一个 Python 列表：

```python
messages = [
    {"role": "system",    "content": "你是一个助手"},
    {"role": "user",      "content": "你好"},
    {"role": "assistant", "content": "你好，有什么可以帮你？"},
    {"role": "user",      "content": "我叫张三"},
    ...
]
```

每次调 API，**这个列表的全部内容**都会重新发给模型。模型看到什么取决于列表里有什么：

- 列表里有 → 模型"记得"
- 列表里没有 → 模型失忆

### 1.3 三条推论（重要，后面一切源于此）

1. **"LLM 有记忆"是假象**——记忆 = 你在 append 列表。
2. **让 LLM"忘掉"某事** = 从列表里 pop 那几条，没有"遗忘 API"。
3. **"让模型做新事"的唯一方式** = 往列表里塞新内容（用户输入、工具结果、摘要）。

### 1.4 踩坑实录

> 一次性发多条连续 user 消息（没有 assistant 夹在中间），模型可能会**一次回答里把几个问题全答了**——因为它看到的结构异常，会自己脑补"我要把欠着的都答掉"。
>
> **启示**：模型对消息结构高度敏感。保证 user/assistant/tool 的顺序合法，是 agent 工程的基本功。

---

## 2. Step 1：最朴素的对话

### 2.1 目标

跑通 LLM API，理解 messages 列表。

### 2.2 最小代码骨架

```python
import os, json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    api_key=os.environ["ARK_API_KEY"],
    base_url="https://ark.cn-beijing.volces.com/api/v3",
)
MODEL = os.environ["ARK_MODEL"]  # 推荐用 ep-xxx 推理接入点 ID

messages = [{"role": "system", "content": "你是一个简洁的助手"}]

while True:
    user_input = input("你：").strip()
    if user_input in {"exit", "quit", ""}: break

    messages.append({"role": "user", "content": user_input})
    resp = client.chat.completions.create(model=MODEL, messages=messages)
    reply = resp.choices[0].message.content
    messages.append({"role": "assistant", "content": reply})
    print(f"助手：{reply}\n")
```

### 2.3 关键实验

| 实验 | 做法 | 观察到的现象 | 学到什么 |
|---|---|---|---|
| A | 调 LLM 前 `print(json.dumps(messages, ensure_ascii=False, indent=2))` | 列表每轮线性增长 | messages 是状态的唯一载体 |
| B | 注释掉 `messages.append({"role": "assistant", ...})` | 助手说了啥下一轮就"忘" | 记忆 = append 操作 |
| C | `print(resp.model_dump_json(indent=2))` | 看到 `choices`/`usage`/`finish_reason`/`tool_calls` 等字段 | 原始结构远比 `.content` 丰富 |

### 2.4 实验 B 的正确验证剧本

很多人会被"模型还是答对了"误导——那是因为**用户自己把答案说过**，信息在 user 消息里。要真正看到失忆，**必须让关键信息只存在于 assistant 回复里**：

```
你：请随机给我起一个英文名，就定一个
助手：Michael（或别的）
你：我刚才那个英文名叫什么？   ← 此时它会答不出来
```

### 2.5 `resp` 里值得记住的四个字段

| 字段 | 含义 | 什么时候看 |
|---|---|---|
| `choices[0].message.content` | 模型生成的文本 | 平时看这个 |
| `choices[0].message.tool_calls` | 工具调用请求 | Step 3 之后关键 |
| `choices[0].finish_reason` | 为什么停下来：`stop` / `tool_calls` / `length` | 做监控/调错/流程控制 |
| `usage.prompt_tokens` / `completion_tokens` | token 消耗 | 算成本、做限流 |

### 2.6 自测

1. 聊 10 轮后第 11 轮只发"嗯"，实际 prompt_tokens 大概是多少？
2. 为什么 system 消息一般只放开头一条？
3. 怎么让助手忘掉之前某段对话？

**参考答案**：
1. ≈ 前 10 轮所有 user/assistant 内容 + system + "嗯" 的 token 总和（每多聊一轮下一轮 prompt 就重一点）。
2. 模型训练时 system 就在开头；中途插 system 不是不行但效果不稳，工程上也乱。
3. 从 messages 里把那几条 pop 掉即可。

---

## 3. Step 2：手搓工具调用（不用任何 tool_use API）

### 3.1 目标

**不依赖任何 SDK 特性**，纯靠 prompt + 字符串解析，让 LLM 学会调工具。理解工具调用的原始骨头。

### 3.2 核心思想

1. 在 system prompt 里**约定一个协议**：想调工具时输出 `<tool_call>{"name":..., "args":...}</tool_call>`。
2. 宿主代码用正则捕获这段文本。
3. 解析 JSON、执行工具、把结果伪装成 user 消息塞回 messages。
4. 再问 LLM。
5. 循环直到 LLM 输出普通文本（不再请求工具）。

### 3.3 关键代码片段

```python
SYSTEM_PROMPT = """你是一个助手。你可以使用以下工具：
- get_weather(city: str)

需要工具时，**必须且只能**输出如下格式：
<tool_call>
{"name": "工具名", "args": {...}}
</tool_call>
不需要时正常用自然语言回答。"""

TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

def parse_tool_call(text):
    m = TOOL_CALL_PATTERN.search(text)
    if not m: return None
    data = json.loads(m.group(1))
    return data["name"], data.get("args", {})

# 主循环:
for step in range(5):
    resp = client.chat.completions.create(model=MODEL, messages=messages)
    text = resp.choices[0].message.content
    messages.append({"role": "assistant", "content": text})

    call = parse_tool_call(text)
    if call is None:                       # 不调工具 → 最终回答
        return text
    name, args = call
    result = TOOLS[name](**args)           # 宿主代码真的执行工具
    messages.append({"role": "user",       # 用 user 角色伪装塞回
                     "content": f"<tool_result>{result}</tool_result>"})
```

### 3.4 一次完整循环长这样

```
[LLM] <tool_call>{"name": "get_weather", "args": {"city": "北京"}}</tool_call>
[宿主] 解析 → 执行 get_weather("北京") → "晴, 32°C"
[宿主] 把 "<tool_result>晴, 32°C</tool_result>" 塞进 messages
[LLM] 北京今天晴，32°C，有点热。
```

### 3.5 Step 2 的四个痛点（也是 Step 3 要解决的）

| 痛点 | 什么时候暴露 |
|---|---|
| 正则匹配脆弱 | 模型输出"好的，让我查：`<tool_call>...`"时可能解析失败 |
| prompt 教规则不稳 | 长对话后 system 被稀释，模型可能忘格式 |
| 用 user 角色伪装工具结果 | 模型偶尔会以为是用户说的话 |
| prompt 里堆工具说明 | 10 个工具 prompt 就爆炸 |

### 3.6 黄金认知

> **Prompt 就是协议。协议写得越死，模型行为越稳。**
>
> 所有框架级 agent 的 system prompt 动辄几千字，不是啰嗦，是在防这种"协议失守"的崩溃。

---

## 4. Step 3：用官方 tool_use API

### 4.1 目标

用结构化接口把 Step 2 的手搓流程替换掉。**核心循环一模一样**，只是接口变干净了。

### 4.2 结构化工具声明

工具从"写在 prompt 里"升级为"作为参数传入"：

```python
TOOLS_SCHEMA = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的当前天气",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名"}
            },
            "required": ["city"],
        },
    },
}]
```

### 4.3 主循环模板（记下来，以后照抄）

```python
for step in range(MAX_STEPS):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS_SCHEMA,
        tool_choice="auto",          # 让模型自主决定用不用工具
    )
    msg = resp.choices[0].message
    messages.append(msg.model_dump(exclude_none=True))

    if not msg.tool_calls:           # 没有工具调用 → 最终回答
        return msg.content

    for tc in msg.tool_calls:        # 一轮可能有多个工具调用
        name = tc.function.name
        args = json.loads(tc.function.arguments)
        result = TOOLS_IMPL[name](**args)
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,   # 必须对应,否则 API 报错
            "content": str(result),
        })
```

### 4.4 四个关键变化

| 维度 | Step 2 | Step 3 |
|---|---|---|
| 工具声明 | 写在 prompt 里 | `tools` 参数（JSON Schema） |
| 模型表达调用 | 输出 `<tool_call>` 文本 | `message.tool_calls` 结构化字段 |
| 宿主解析 | 正则 + `json.loads` | 直接读字段 |
| 结果回传 | 伪装成 user 消息 | `role: "tool"` 专属消息 + `tool_call_id` |

### 4.5 规范的 messages 结构（记下来，所有主流模型通用）

```json
[
  {"role": "system",    "content": "..."},
  {"role": "user",      "content": "北京今天热吗？"},
  {"role": "assistant", "content": null,
   "tool_calls": [{"id": "call_abc", "type": "function",
                   "function": {"name": "get_weather",
                                "arguments": "{\"city\":\"北京\"}"}}]},
  {"role": "tool",      "tool_call_id": "call_abc",
   "content": "晴, 32°C"},
  {"role": "assistant", "content": "北京今天晴，32°C。"}
]
```

**每个 tool_calls 必须有对应 tool_call_id 的 tool 消息配对**，否则 API 报错。这是 agent 工程里最常见的 bug 来源。

### 4.6 `finish_reason` 的三种值

- `stop`：模型正常输出完文本（最终回答）
- `tool_calls`：模型想调工具才停的（要进下一轮）
- `length`：撞到 max_tokens 被截断（要扩容或压缩）

### 4.7 `tool_choice` 的几种值

- `"auto"`：模型自己决定用不用（默认）
- `"none"`：禁止调工具（有时需要强制让它用自然语言回答）
- `"required"`：必须调一个工具（适合"必须拿外部信息"的场景）
- `{"type": "function", "function": {"name": "xxx"}}`：强制调指定工具

---

## 5. Step 4：工业级 Agent 的最小骨架

### 5.1 目标

从 demo 走向"能用"。加入多工具、trace 日志、边界处理、安全沙箱、循环保护。

### 5.2 架构总览

```
┌──────────────────────────────────────────┐
│             User Input                   │
└────────────────────┬─────────────────────┘
                     ▼
┌──────────────────────────────────────────┐
│  while step < MAX_STEPS:                 │
│    resp = LLM(messages, tools)           │
│    if not tool_calls: return reply       │
│    for each tool_call:                   │
│        执行工具 (含边界处理)              │
│        结果塞回 messages                 │
└──────────────────────────────────────────┘
```

### 5.3 工具设计三原则（比 prompt 工程更底层）

1. **工具要"正交"**——功能不重叠，否则模型选择纠结
2. **description 是写给模型看的**——"什么场景用 + 什么场景不用 + 关键词铺一些"
3. **错误也是返回值**——工具里 `except` 最终要 **把错误转成字符串**喂回模型，让它自己读懂自己修正；**不要 raise 到主循环**

**好 description 模板**：
```
执行 XX 操作。
适用场景：<列举两三个>
不适用：<列举一两个反例>
关键词：<铺几个用户可能用的词>
```

### 5.4 完整 Step 4 代码结构

分五块：

```python
# 1. 安全沙箱(_safe_path):限制文件访问范围
# 2. 工具实现(get_current_time / calculator / read_file / list_dir)
# 3. 工具声明(TOOLS_SCHEMA,JSON Schema 列表)
# 4. Tracer 类(把每步落盘成 JSONL)
# 5. 主循环(三层边界处理 + MAX_STEPS 保护)
```

完整代码 200 行左右，见 `step4_agent.py`。

### 5.5 三层边界处理（生产级必备）

```python
for tc in msg.tool_calls:
    # 边界 1: 参数 JSON parse 失败(模型输出了坏的 JSON)
    try:
        args = json.loads(tc.function.arguments)
    except json.JSONDecodeError as e:
        # ✅ 不要 raise,把错误信息作为 tool 结果喂回,保留 tool_call_id
        result = f"参数解析失败:{e}。原始参数:{tc.function.arguments}"
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        continue

    # 边界 2: 未知工具(模型幻觉出了不存在的工具名)
    if name not in TOOLS_IMPL:
        result = f"未知工具 {name}。可用:{list(TOOLS_IMPL.keys())}"
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        continue

    # 边界 3: 工具执行抛异常(网络错、权限错、bug)
    try:
        result = TOOLS_IMPL[name](**args)
    except Exception as e:
        result = f"工具执行异常:{e}"
    # 再 append
```

**核心原则**（请刻进脑子）：

> **Agent 里所有 `except` 都应以"把错误作为 observation 喂回模型"结尾**，而不是 raise 出去让主循环崩。模型比你想象的会修 bug——只要你给它足够的信息和机会。

### 5.6 安全沙箱原则

```python
def _safe_path(user_path: str) -> Path:
    p = (WORKSPACE / user_path).resolve()
    if not str(p).startswith(str(WORKSPACE.resolve())):
        raise ValueError("路径越界")
    return p
```

**黄金规则**：
> **Agent 安全永远是"代码边界在外，模型自觉在内"的双层防御。**
> 只靠 prompt 里写"不要读 /etc/passwd" 是不够的——越狱 prompt 会绕过；代码级拦截才是最后防线。

### 5.7 Trace 日志（Agent 可观测性的底座）

```python
class Tracer:
    def log(self, event: str, data: dict):
        record = {"time": datetime.now().isoformat(timespec="seconds"),
                  "event": event, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
```

**要记录的 event 类型**：
- `user_input`：用户输入
- `llm_response`：每次 LLM 调用（含 content、tool_calls、usage、finish_reason、latency）
- `tool_call` / `tool_result` / `tool_error`：工具执行三种状态
- `final_answer`：最终回答
- `max_steps_exceeded`：被循环上限截断

**为什么 JSONL 而不是 JSON**：每一行一个独立事件，可以 `tail -f` 实时看、可以 `jq` 过滤，也不怕写一半进程挂了导致整个文件坏掉。**所有生产级 agent（Cursor、Claude Code、OpenDevin）都用类似格式**。

**读 trace 是 agent 工程师最核心的技能**——比写 prompt 还重要。每次 agent 行为异常，先读 trace，从 LLM 原始输出和工具结果里推断它为什么这么决策。

### 5.8 MAX_STEPS 保护

永远给 `while` 循环加上界。否则模型可能因为:
- 长对话后"迷失"、一直无意义调同一个工具
- 参数写错陷入"改错 → 再错 → 再改"的无限循环
- 模型 bug 输出永远不终止

`MAX_STEPS=10` 对大多数任务够用。超出直接停，记录下来后续分析。

---

## 6. 四个贯穿始终的 Agent 工程原则

汇总一下，这四条是从 Step 1 到 Step 4 反复出现的底层原理：

### 原则 1：messages 列表承载全部状态

没有别的地方藏着什么"记忆"或"上下文"。所有状态管理 = 操作这个列表。

### 原则 2：Prompt 就是协议

- system prompt 是工作合同，写得越死，模型越稳。
- 工具 description 是选择工具的唯一依据，写成"场景 + 反例 + 关键词"。

### 原则 3：错误即 observation

不要 raise，把错误字符串喂回模型当工具结果。模型 70% 的错误能自己修。

### 原则 4：代码沙箱 >> 模型自觉

安全边界必须在代码层，不能只靠 prompt 约束。模型配合是锦上添花，代码拦截是兜底保险。

---

## 7. Token 成本的二次方规律

**单轮**：prompt_tokens 随对话轮数线性增长（每轮累加约 k 个 token）。

**累计**：整个会话总 token 消耗是：
$$\sum_{i=1}^{n} k \cdot i = \frac{k \cdot n(n+1)}{2} \approx O(n^2)$$

**实战影响**：
- 聊 100 轮 vs 10 轮，总成本差 **100 倍**（不是 10 倍）。
- 这是为什么生产级 agent 都要做上下文压缩——不是"撑不下了再压"，是**主动定期压**。

**四种大文件处理策略**：

| 策略 | 适用场景 |
|---|---|
| 截断 + 告知 | 只需看开头（判断文件类型、看 header） |
| 分页 offset/limit | Agent 遍历但不需要一次性看完 |
| Grep 式检索 | 大文件但只需匹配几行（**Claude Code 的默认策略**） |
| Summary 压缩 | 必须理解整体但细节不重要 |

**反直觉的核心原则**：
> **token 比 IO 贵得多**。宁可让 agent 多调几次工具精准取信息，也别一次性塞大文件进上下文。

---

## 8. 常见坑位清单

| 坑 | 症状 | 解法 |
|---|---|---|
| 忘 append assistant 消息 | 助手失忆 | 无论是否调工具都要 append `msg.model_dump()` |
| tool_call 没有对应 tool 消息 | API 报 `tool_call_id not found` | 每个 tool_call 都要配对一个 tool 结果 |
| `msg.model_dump()` 保留了 null 字段 | 发回 API 时报字段错 | 用 `exclude_none=True` |
| 多条连续 user 消息 | 模型一次答多个问题 | 保证 user/assistant 交替 |
| except 直接 raise | Agent 经常崩 | 改成 "错误 → 工具结果 → 喂回模型" |
| 工具 description 太简短 | 模型不调 / 错调 | "场景 + 反例 + 关键词"三段式 |
| 没有 MAX_STEPS | 死循环烧钱 | 强制上限 10 步 |
| 靠 prompt 做安全 | 被越狱绕过 | 必须加代码级沙箱 |
| `.env` 变成 `.env.txt`（Windows） | 环境变量加载不到 | 资源管理器开启"显示扩展名" |
| 用预置 Model ID 报 404 | 账号没权限直接调 | 建"推理接入点"拿 `ep-xxx` ID |

---

## 9. Agent 行为的典型现象（从你自己的 trace 里总结）

这些是你在 Step 4 跑任务时亲眼看到的，值得单独记住：

### 9.1 "同输入反复试"现象

模型碰到工具返回"不存在"时，可能连续尝试 `READ` → `README` → `readme` → `README.md` 多个变体，**但不会主动换工具**（比如用 list_dir 探测）。这说明模型会改参数但**不会自发跳层反思**——要靠 prompt 或循环检测引导。

### 9.2 "Lazy Agent" 现象

长对话里模型可能输出"继续调用..."这种承诺语，但 `tool_calls` 字段其实是空——**说一套做一套**。这是模型对重复模式"懈怠"的表现。解法：循环检测 + 主动打断。

### 9.3 自审查比预期严

"读 /etc/passwd" 这类请求，模型往往直接**拒绝而不调用工具**（看过 system prompt 后自己判断）。这很好但**不要完全依赖**——越狱 prompt 可能绕过，代码沙箱必须存在。

### 9.4 多工具并行

问"北京和上海哪个热"时，模型可能**一轮返回两个 tool_calls**（`msg.tool_calls` 长度为 2），也可能分两轮串行。两种都合法。生产代码要支持"一轮多工具"的遍历。

---

## 10. 到这里，你已经拥有什么

一个 **~200 行** 的 agent，具备：
- 多工具自主规划
- 完整 trace 可观测性
- 三种边界错误处理
- 安全沙箱
- 循环步数保护

这个骨架和 **smolagents / Cline / OpenHands** 的内核几乎一致。区别只是：
- 它们的工具更多（shell、browser、web、sql...）
- 它们的 prompt 更长（几千字）
- 它们有 UI 和云端支持

**把你这个脚本换个皮，就是一个能跑的产品**。剩下的 Step 5 要加的东西：

- **循环检测** + **失败升级 prompt**（治"同参数反复试"和"Lazy Agent"）
- **上下文压缩**（治二次方 token 增长，让 agent 能跑长任务）

---

## 11. 建议的复习路径

1. **第一遍**：把本文档读完，不看代码。
2. **第二遍**：打开 `step4_agent.py`，对照第 5 节把代码和文档对应起来。
3. **第三遍**：合上代码，自己从头写一遍 Step 3（最小可用的 tool_use agent），不要复制粘贴。
4. **第四遍**：给它加一个新工具（比如 `write_file` 或 `http_get`），注意 description 和边界处理。
5. **到这一步**，你再去读 smolagents 源码，会发现"哦这跟我写的一样"——此时就可以开始 Step 5 了。

---

## 12. 速查表：一屏看懂 Agent 循环

```
┌─────────────────────────────────────────────────────┐
│  messages = [{"role": "system", "content": "..."}]  │
│  for step in range(MAX_STEPS):                      │
│    ┌───────────────────────────────────────────┐   │
│    │ resp = LLM(messages, tools=TOOLS_SCHEMA)  │   │
│    │ msg = resp.choices[0].message             │   │
│    │ messages.append(msg.model_dump(           │   │
│    │                   exclude_none=True))     │   │
│    │                                           │   │
│    │ if not msg.tool_calls:                    │   │
│    │     return msg.content  ← 最终回答        │   │
│    │                                           │   │
│    │ for tc in msg.tool_calls:                 │   │
│    │     try: args = json.loads(...)           │   │
│    │     except: 错误喂回;continue            │   │
│    │                                           │   │
│    │     if name not in TOOLS: 错误喂回;continue│  │
│    │                                           │   │
│    │     try: result = TOOLS[name](**args)     │   │
│    │     except Exception as e:                │   │
│    │         result = f"异常:{e}"              │   │
│    │                                           │   │
│    │     messages.append({                     │   │
│    │       "role": "tool",                     │   │
│    │       "tool_call_id": tc.id,              │   │
│    │       "content": result})                 │   │
│    └───────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

---

**下次继续 Step 5 时，从这份文档第 10 节开始续写即可。**
