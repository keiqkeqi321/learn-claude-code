# s04: Subagents（子智能体）

`s01 > s02 > s03 > [ s04 ] s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12`

> *“把大任务拆小；每个子任务拿到干净上下文”*：子智能体使用独立的 `messages[]`，不会污染主对话。
>
> **Harness 层**：上下文隔离，用来保护模型思路的清晰度。

## 问题

随着智能体不断工作，`messages` 数组会越来越大。每次读文件、每次执行 `bash` 的输出，都会一直留在上下文里。

比如，“这个项目使用什么测试框架？”这个问题，也许需要读 5 个文件；但父智能体真正需要的，可能只是最后一个词：`pytest`。

## 解决方案

```
Parent agent                     Subagent
+------------------+             +------------------+
| messages=[...]   |             | messages=[]      | <-- fresh
|                  |  dispatch   |                  |
| tool: subagent   | ----------> | while tool_use:  |
|   prompt="..."   |             |   call tools     |
|                  |  summary    |   append results |
|   result = "..." | <---------- | return last text |
+------------------+             +------------------+

Parent context stays clean. Subagent context is discarded.
```

父智能体上下文保持整洁。子智能体的上下文在结束后被丢弃。

## 工作原理

1. 父智能体拥有一个 `subagent` 工具。
   `Explore` 模式下，子智能体拥有只读子工具：`bash`、`read_file`、`load_skill`。
   `general-purpose` 模式下，还会额外获得 `write_file` 和 `edit_file`。
   仍然禁止递归生成新的子智能体。

```python
PARENT_TOOLS = CHILD_TOOLS + [
    {"name": "subagent",
     "description": "Spawn a subagent with fresh context.",
     "input_schema": {
         "type": "object",
         "properties": {"prompt": {"type": "string"}},
         "required": ["prompt"],
     }},
]
```

2. 子智能体从独立的 `messages=[]` 开始，运行自己的循环。只有最终文本会返回给父智能体。

```python
def run_subagent(prompt: str) -> str:
    sub_messages = [{"role": "user", "content": prompt}]
    for _ in range(30):  # safety limit
        response = client.messages.create(
            model=MODEL, system=SUBAGENT_SYSTEM,
            messages=sub_messages,
            tools=CHILD_TOOLS, max_tokens=8000,
        )
        sub_messages.append({"role": "assistant",
                             "content": response.content})
        if response.stop_reason != "tool_use":
            break
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                output = handler(**block.input)
                results.append({"type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output)[:50000]})
        sub_messages.append({"role": "user", "content": results})
    return "".join(
        b.text for b in response.content if hasattr(b, "text")
    ) or "(no summary)"
```

子智能体的完整消息历史会被丢弃，即使它中间执行了很多轮工具调用。父智能体收到的只是一个普通 `tool_result` 里的摘要文本。

## 执行模式

- 在 `accept_edits` 下，主智能体可以直接调用 `subagent`。
- 在 `shortcuts` 和 `plan` 下，`subagent` 仍然需要先 `request_authorization`，或者先切换模式。
- 可写子智能体只在 `accept_edits` 和 `yolo` 下直接可用；在只读模式中仍然受限。
- 一旦进入子智能体循环，子智能体已注册的工具会在子智能体边界内执行，不会再按主智能体普通工具调用的方式被拦截。

## 相对 s03 的变化

| 组件 | 之前（s03） | 之后（s04） |
|------|-------------|-------------|
| Tools | 5 | 5（基础）+ `subagent`（仅父端） |
| 上下文 | 单一共享 | 父 + 子隔离 |
| Subagent | 无 | `run_subagent()` 函数 |
| 返回值 | 不适用 | 仅摘要文本 |

## 试一试

```sh
cd learn-claude-code
python agents/s04_subagent.py
```

可以试试这些 prompt：

1. `Use a subagent to find what testing framework this project uses`
2. `Delegate: read all .py files and summarize what each one does`
3. `Use a subagent to create a new module, then verify it from here`
