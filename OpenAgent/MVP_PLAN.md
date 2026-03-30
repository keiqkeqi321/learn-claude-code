# OpenAgent CLI MVP Plan

## 1. Goal

基于 `agents/s_full.py` 的成熟机制，演化出一个类似 Claude Code 的 AI Agent CLI 工具 `OpenAgent`。

本次 MVP 的前提只有三条：

1. 必须完整覆盖 `s_full.py` 的全部现有能力，而不是只做其中的单 Agent 子集。
2. 在“全能力覆盖”前提下，通过模块化、持久化、协议闭环、并发控制和错误恢复来保证系统稳定性。
3. 在与 `s_full.py` 全能力对齐之后，只新增两个方向：
   - MCP Server 集成
   - OpenAI API 配置兼容


## 2. Source Analysis Summary

### 2.1 `s_full.py` 的核心设计点

`s_full.py` 不是“一个大脚本”，而是一个完整 Agent Harness 的单文件参考实现，核心由以下设计点组成：

1. 不变的 Agent Loop
   - `agent_loop(messages)` 是系统内核。
   - 协议固定：`messages -> model -> tool_use -> tool_result -> continue`。
   - 这部分必须完整保留，不能被业务逻辑污染。

2. Typed Tool Dispatch
   - `TOOLS` 负责模型可见 schema。
   - `TOOL_HANDLERS` 负责本地真实执行。
   - 新能力通过“注册工具”接入，而不是改 loop。

3. Workspace Boundary
   - `safe_path()` 限制文件操作不能逃出工作区。
   - 这是 CLI 工具的最小安全边界，必须保留。

4. 双层任务系统
   - `TodoManager` 解决当前会话内的短期步骤跟踪。
   - `TaskManager` 解决跨轮次、可恢复的持久任务图。
   - 这是 `s_full.py` 里最重要的稳定性设计之一。

5. Subagent 隔离执行
   - `run_subagent()` 用独立上下文执行子任务，只把摘要返回主 Agent。
   - 这是保持主上下文干净的关键能力，必须保留。

6. Skill 按需加载
   - 技能名只出现在系统提示里。
   - 技能正文通过工具结果按需加载。
   - 这是降低 token 压力的重要设计。

7. Context Compact
   - `microcompact()`：低损耗微压缩。
   - `auto_compact()`：阈值触发，落盘 transcript 后再总结。
   - 这是长会话稳定运行的必要条件。

8. Background Tasks
   - 慢命令异步执行，结果通过通知队列回注。
   - 主 loop 保持单线程，只有外部执行并发。

9. Team / Inbox / Protocol
   - `MessageBus`、`TeammateManager`、shutdown/plan protocol、`idle/claim_task` 都是 `s_full.py` 的正式能力面。
   - 这部分不能从 MVP 剔除，正确做法是稳定化和产品化，而不是降级为后续能力。


### 2.2 文档演化结论

`docs/s01 -> s12` 的演化路径很清晰：

1. `s01-s02` 固定了极小内核：循环 + 工具分发。
2. `s03-s06` 解决单 Agent 稳定性：计划、隔离、技能、压缩。
3. `s07-s08` 解决持久执行面：任务图、后台任务。
4. `s09-s11` 把协作从 prompt 技巧升级为文件驱动的多 Agent 状态机。
5. `s12` 进一步引入 worktree 级目录隔离，但这一步没有进入 `s_full.py`。

结论：

1. 实现顺序仍然应该遵循演化顺序：先固化 loop，再补状态、协作和隔离。
2. 但产品目标不能截断在 `s07` 或 `s08`，而应以 `s_full.py` 全能力对齐为 MVP 发布门槛。
3. 真正应该延后的，是 `s12 worktree isolation` 这类明确超出 `s_full.py` 能力面的后续扩展。
4. 最该保留并稳定化的是：稳定 loop、持久状态、可压缩上下文、可追踪执行、可恢复协作。


## 3. MVP Scope

### 3.1 MVP 必须包含

1. 单 Agent CLI 主循环
2. 文件/命令基础工具
3. TodoWrite
4. 持久任务系统
5. Subagent
6. Skill Loader
7. Context Compact
8. Background Tasks
9. MessageBus / inbox
10. TeammateManager
11. shutdown_request / plan_approval / send_message / broadcast / read_inbox
12. idle / claim_task / list_teammates
13. Anthropic Provider
14. OpenAI Provider
15. MCP Server 集成
16. transcript / logs / session / team state 持久化


### 3.2 MVP 不新增的复杂度

1. `s12` 的 Git worktree 隔离
2. 超出 `s_full.py` 的更复杂多团队编排
3. 远程 MCP transport 的复杂兼容
4. OAuth / 云端多租户能力
5. GUI / TUI


### 3.3 原则

MVP 不是“只保留 `s_full.py` 的核心子集”，而是“完整覆盖 `s_full.py` 全能力，并把风险最大的耦合拆开”。


## 4. Target Product Shape

`OpenAgent` 第一版建议做成一个清晰的 CLI：

```text
openagent chat
openagent run "fix tests in this repo"
openagent tasks list
openagent tasks get 3
openagent compact
openagent doctor
```

REPL 内保留最小运维命令：

```text
/compact
/tasks
/team
/inbox
/bg
/help
/exit
```

说明：

1. `chat` 是交互主入口。
2. `run` 用于单次非交互任务。
3. `tasks` 用于查看持久任务图。
4. `team` 用于查看 teammate 状态。
5. `inbox` 用于查看 lead inbox。
6. `doctor` 用于检查 Provider、MCP、工作区与权限配置。


## 5. Recommended Architecture

### 5.1 分层

建议把 `OpenAgent` 切成 7 层：

1. CLI Layer
   - 参数解析
   - REPL
   - 用户命令

2. Runtime Layer
   - Agent loop
   - 消息状态
   - 事件注入
   - compact 流程

3. Tool Layer
   - tool schema registry
   - tool execution registry
   - filesystem/shell/todo/task/subagent/background/team/mcp tools

4. Provider Layer
   - Anthropic adapter
   - OpenAI adapter
   - 统一输出为同一套 `AssistantTurn` / `ToolCall` 抽象

5. Storage Layer
   - transcript store
   - task store
   - session store
   - background job state
   - inbox / team state

6. Integration Layer
   - skills
   - MCP server registry / client
   - provider-specific adapters

7. Collaboration Layer
   - message bus
   - teammate runtime
   - inbox protocol
   - approval / shutdown coordination


### 5.2 建议目录

```text
OpenAgent/
  MVP_PLAN.md
  pyproject.toml
  README.md
  .env.example
  openagent/
    cli/
      main.py
      repl.py
      commands.py
    runtime/
      agent.py
      session.py
      messages.py
      compact.py
      events.py
      teammate.py
    providers/
      base.py
      anthropic_provider.py
      openai_provider.py
    tools/
      registry.py
      filesystem.py
      shell.py
      todo.py
      tasks.py
      subagent.py
      background.py
      team.py
      mcp.py
    mcp/
      registry.py
      client.py
      transport_stdio.py
    skills/
      loader.py
    storage/
      tasks.py
      transcripts.py
      sessions.py
      jobs.py
      inbox.py
      team.py
    collaboration/
      bus.py
      protocols.py
      trackers.py
    config/
      settings.py
      models.py
```


## 6. Capability Mapping From `s_full.py`

### 6.1 必须原样保留的能力

| `s_full.py` 能力 | MVP 保留方式 |
|---|---|
| `agent_loop()` | 原样保留为 `runtime/agent.py` 的核心循环 |
| `safe_path()` | 原样保留为工作区边界守卫 |
| `read/write/edit/bash` | 原样保留，但拆到 `tools/` |
| `TodoManager` | 原样保留，仍然作为短期会话规划工具 |
| `TaskManager` | 原样保留，但做线程安全与存储封装 |
| `run_subagent()` | 原样保留为轻量一次性子代理 |
| `SkillLoader` | 原样保留 |
| `microcompact/auto_compact` | 原样保留，提升可配置性 |
| `BackgroundManager` | 原样保留，但补统一安全策略 |
| `MessageBus` | 原样保留，但补消息持久化一致性和并发控制 |
| `TeammateManager` | 原样保留，但补生命周期管理和恢复逻辑 |
| `shutdown_request / plan_approval / read_inbox / broadcast` | 原样保留，补协议闭环与状态跟踪 |
| `idle / claim_task / list_teammates` | 原样保留 |
| REPL commands | 原样保留并补 `/team`、`/inbox` 的稳定交互 |


### 6.2 必须重构但语义保留的能力

| `s_full.py` 能力 | 重构方向 |
|---|---|
| `client = Anthropic(...)` | 抽象成 Provider 接口 |
| `MODEL = os.environ[...]` | 抽象成配置系统 |
| `TOOL_HANDLERS + TOOLS` | 抽象成 ToolRegistry |
| `SYSTEM` 静态字符串 | 抽象成 PromptAssembler |
| `auto_compact()` | 抽象成可配置 compact strategy |
| 全局单例 | 抽象成 AppContext / RuntimeContext |
| `MessageBus` | 抽象成 InboxStore + Bus interface |
| `TeammateManager._loop()` | 抽象成 TeammateRuntime |
| shutdown / plan protocol 状态 | 抽象成 RequestTracker |


### 6.3 延后到 V1.1+ 的能力

| 能力 | 原因 |
|---|---|
| `s12 worktree isolation` | 超出 `s_full.py` 当前能力面 |
| 多工作区调度中心 | 不属于现阶段 CLI MVP |
| 自定义远程 transport MCP 套件 | 超出最小集成范围 |


## 7. Provider Strategy

### 7.1 统一 Provider 接口

定义一个最小 Provider 抽象：

```python
class LLMProvider(Protocol):
    def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
    ) -> AssistantTurn: ...
```

返回统一结构：

```python
AssistantTurn(
  stop_reason="tool_use|end_turn|max_tokens|error",
  text_blocks=[...],
  tool_calls=[...],
  raw_response=...
)
```


### 7.2 Anthropic 兼容

直接映射现有 `s_full.py` 行为：

1. `ANTHROPIC_API_KEY`
2. `ANTHROPIC_BASE_URL`
3. `MODEL_ID`


### 7.3 OpenAI 兼容

新增 OpenAI 配置：

1. `OPENAI_API_KEY`
2. `OPENAI_BASE_URL`
3. `OPENAI_MODEL`
4. `OPENAI_ORG` 可选

实现策略：

1. 在 Provider 层做适配，不改 Runtime Loop。
2. 把 OpenAI 的函数调用结果转成统一 `tool_calls` 抽象。
3. 所有 Provider 都输出一致的 `stop_reason` 语义。

注意：

1. OpenAI 兼容的目标是“配置兼容 + 行为兼容”，不是把 Runtime 改成跟着 SDK 走。
2. 如果不同 Provider 对工具调用细节有差异，差异只能存在于 `providers/` 内部。


## 8. MCP Strategy

### 8.1 MVP 对 MCP 的定义

MVP 里“加上 MCP Server 功能”建议解释为：

`OpenAgent` 作为 MCP Client，能够连接和使用外部 MCP Server 暴露的工具。

这更接近 Claude Code 的实际使用方式，也能避免第一版就同时承担“做 CLI”和“做自己的 MCP Server 平台”的双重复杂度。


### 8.2 MVP 只做最小 MCP 集成

1. 仅支持 `stdio` transport
2. 仅支持静态配置的 server registry
3. 启动时发现并注册 MCP tools
4. 把 MCP tool 暴露进统一 ToolRegistry
5. 保留调用日志和错误回传


### 8.3 不做的 MCP 复杂项

1. OAuth / 动态授权
2. 复杂远程 transport
3. 多租户隔离
4. MCP Server 生命周期的复杂热更新
5. 自身暴露为 MCP Server


### 8.4 MCP 配置建议

建议使用 `openagent.toml`：

```toml
[provider]
name = "anthropic"
model = "claude-sonnet-4-6"

[[mcp_servers]]
name = "filesystem"
transport = "stdio"
command = "python"
args = ["server.py"]
cwd = "D:/tools/mcp-filesystem"
enabled = true
```


## 9. Stability Hardening Requirements

这是 MVP 成败的关键部分。

### 9.1 必做稳定性修复

1. 所有持久化存储统一封装
   - 不允许业务代码直接散写 JSON 文件。

2. `TaskManager` 增加锁和原子写
   - 解决 task id、claim、update 的竞态。

3. `MessageBus` / inbox 增加原子追加、读写锁和恢复机制
   - 避免多线程读写丢消息、乱序和 drain 误消费。

4. `TeammateManager` 增加生命周期恢复
   - 进程重启后能够重建 team state 或识别脏状态。

5. `BackgroundManager` 统一复用安全策略
   - 不能让后台命令绕过 shell 安全限制。

6. API 调用错误恢复
   - Provider 超时、429、5xx 要有重试和清晰错误。

7. transcript 与 compact 恢复机制
   - compact 后必须能从 transcript 恢复完整上下文。

8. shutdown / plan protocol 闭环
   - request id、状态跟踪、超时和重试要完整。

9. 工作区显式化
   - 不再依赖 `Path.cwd()` 的隐式行为。
   - CLI 启动时明确确定 workspace root。

10. Session 级观测性
   - 每轮要有 trace id / turn id / tool log。


### 9.2 边界约束

1. 主 Agent loop 仍保持单线程决策。
2. 并发只允许出现在 subprocess / MCP I/O。
3. 子代理仍保持轻量一次性执行。
4. teammate 的自治行为必须受任务图和 inbox 状态约束，不能自由漂移。
5. 默认禁用 destructive shell。
6. 所有 tool result 都要有长度上限。


## 10. Implementation Phases

### Phase 0: Plan Freeze

目标：

1. 锁定“`s_full.py` 全能力覆盖 + 稳定化”的 MVP 边界
2. 冻结超出 `s_full.py` 的非目标能力
3. 确认目录结构与 Provider/MCP 方案

产出：

1. 本计划文档
2. `README` 草案
3. `openagent.toml` 设计草案


### Phase 1: Project Skeleton

目标：

1. 初始化 Python 项目
2. 建立 CLI 入口
3. 建立配置系统
4. 建立基础日志系统

产出：

1. `pyproject.toml`
2. `openagent/cli/main.py`
3. `openagent/config/settings.py`
4. `openagent/runtime/agent.py` 空骨架


### Phase 2: Core Runtime Migration

目标：

1. 把 `s_full.py` 的主 loop 和工具协议平移成模块化 Runtime
2. 保留行为，不先优化“智能”

必做：

1. 消息结构抽象
2. ToolRegistry
3. PromptAssembler
4. 主 loop
5. transcript store

完成标准：

1. CLI 能完成 `chat`
2. 单次工具调用闭环稳定
3. Anthropic provider 可跑通
4. loop 与 tool dispatch 的行为和 `s_full.py` 一致


### Phase 3: Core Capability Migration

目标：

1. 完整迁移 `s_full.py` 的单 Agent 核心能力与状态能力

必做：

1. filesystem/shell tools
2. TodoWrite
3. Task system
4. Subagent
5. Skill loader
6. Context compact
7. Background tasks

完成标准：

1. 连续多轮对话可工作
2. task / todo / compact / subagent 都能跑通
3. transcript 与任务状态重启后可恢复


### Phase 4: Collaboration + Provider + MCP

目标：

1. 补上 `s_full.py` 的协作能力
2. 补上 OpenAI 兼容
3. 补上 MCP 集成

必做：

1. `MessageBus`
2. `TeammateRuntime`
3. `shutdown_request / plan_approval / inbox / broadcast`
4. `idle / claim_task / list_teammates`
5. `AnthropicProvider`
6. `OpenAIProvider`
7. provider config switch
8. MCP stdio transport
9. MCP tool registration

完成标准：

1. 同一 Runtime Loop 可在 Anthropic/OpenAI 下运行
2. teammate / inbox / claim task / shutdown request 可跑通
3. 至少 1 个 MCP Server 可接入并被工具调用


### Phase 5: Hardening

目标：

1. 把 MVP 从“能跑”推进到“稳定可用”

必做：

1. 锁与原子写
2. 错误处理和重试
3. `doctor` 命令
4. session / turn / tool logs
5. 回归测试
6. team/inbox 脏状态修复工具

完成标准：

1. 异常不会直接打崩主进程
2. 长会话不会快速失控
3. 任务与 transcript 不容易损坏
4. 多 teammate 状态在重启与异常中可恢复


### Phase 6: MVP Release

目标：

1. 补齐文档、示例配置和最小使用手册

产出：

1. `.env.example`
2. `openagent.toml.example`
3. `README.md`
4. `CHANGELOG.md`


## 11. Suggested Build Order

推荐按以下顺序实现，避免返工：

1. CLI 骨架
2. 配置系统
3. Anthropic provider
4. 统一 Runtime loop
5. ToolRegistry
6. filesystem + shell tools
7. TodoWrite
8. Task system
9. transcript + compact
10. subagent
11. background tasks
12. message bus + inbox store
13. teammate runtime
14. shutdown / approval / broadcast / claim_task
15. OpenAI provider
16. MCP stdio integration
17. doctor / logs / hardening


## 12. Acceptance Criteria

满足以下条件，才算达到稳定 MVP：

1. 可以通过 `openagent chat` 在工作区内稳定执行多轮编码任务。
2. `s_full.py` 的全部能力都已经覆盖：
   - 文件工具
   - shell 工具
   - TodoWrite
   - task graph
   - subagent
   - skill loading
   - compact
   - background tasks
   - message bus / inbox
   - teammate spawn / list / message / broadcast
   - shutdown request / plan approval
   - idle / claim task
3. 可以通过配置切换 `Anthropic` 与 `OpenAI`。
4. 可以接入至少一个 `stdio` MCP Server 并作为工具使用。
5. 长会话下 transcript、compact、task、team state 恢复正常。
6. 子代理不会污染主上下文。
7. 后台任务结果会被正确回注。
8. teammate 能正确进入 `working -> idle -> working/shutdown` 生命周期。
9. 程序在常见 API/工具错误下不会直接崩溃退出。


## 13. Risks And Decisions

### 风险

1. Provider 行为差异会污染 Runtime
2. MCP 工具 schema 适配可能比预期复杂
3. compact 仍然是有损行为，需要 transcript 兜底
4. shell 安全策略过宽会伤稳定性，过严会伤可用性
5. teammate / inbox 并发一致性是最大的工程风险之一
6. `s_full.py` 中未完全闭环的协议逻辑需要在产品层补全


### 决策

1. MVP 必须覆盖 `s_full.py` 的全能力，而不是缩减范围
2. MVP 不做 `s12 worktree isolation`
3. MCP 只做 client 能力，不做 server hosting
4. Provider 差异全部锁在 adapter 层
5. Runtime loop 尽量保持和 `s_full.py` 语义一致
6. team / inbox / protocol 必须做稳定化，不允许仅保留名义接口


## 14. Next Step Recommendation

下一步不建议无序开写全部功能，而应按以下顺序推进：

1. 先在 `OpenAgent` 下搭骨架与配置系统
2. 第一时间把 `s_full.py` 的主 loop 迁移出来
3. 先完成 Anthropic 路径，确保行为与 `s_full.py` 对齐
4. 接着补 team / inbox / protocol，做到和 `s_full.py` 对齐
5. 再接 OpenAI 和 MCP
6. 最后做 hardening 和 CLI 体验收尾


## 15. One-Sentence Summary

`OpenAgent` 的正确演化路线不是“削减 `s_full.py` 的范围来换稳定”，而是“完整覆盖 `s_full.py` 的全部能力，并通过模块化、持久化、协议闭环和并发控制把这些能力做稳定，再以最小额外复杂度接入 OpenAI 与 MCP”。
