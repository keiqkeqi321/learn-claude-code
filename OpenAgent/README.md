# OpenAgent

OpenAgent is a modular AI agent CLI that ports the full feature set of `agents/s_full.py` into a reusable project layout. It keeps the original loop-and-tools interaction model while adding clearer layering for providers, storage, MCP integration, and teammate orchestration.

## Included in this MVP

- Interactive CLI with `chat`, `run`, `tasks`, `compact`, and `doctor`
- Single-agent loop with tool dispatch
- Filesystem and shell tools with workspace boundaries
- Session-scoped `TodoWrite`
- Persistent task graph
- Isolated subagent execution
- Skill loading from `skills/**/SKILL.md`
- Context micro-compact and transcript-backed auto-compact
- Background shell jobs with notifications
- Message bus, inbox, teammate runtime, shutdown requests, and plan approvals
- Anthropic provider and OpenAI-compatible provider adapters
- MCP client integration over `stdio`
- Persistent sessions, transcripts, inbox, team state, and jobs under `.openagent/`

## Layout

```text
OpenAgent/
  pyproject.toml
  README.md
  .env.example
  openagent.toml.example
  openagent/
    cli/
    collaboration/
    config/
    mcp/
    providers/
    runtime/
    skills/
    storage/
    tools/
```

## Quick Start

1. Install the package in editable mode:

```bash
pip install -e ./OpenAgent
```

2. Copy configuration files if needed:

```bash
cp OpenAgent/.env.example .env
cp OpenAgent/openagent.toml.example openagent.toml
```

3. Run a doctor check:

```bash
python -m openagent --workspace . doctor
```

4. Start chat mode:

```bash
python -m openagent --workspace . chat
```

Or install the console entrypoint and use:

```bash
openagent --workspace . chat
```

## Configuration

Environment variables:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `MODEL_ID`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `OPENAI_ORG`

Optional `openagent.toml`:

```toml
[agent]
name = "OpenAgent"
system_prompt = """你是一个专业的AI助手..."""  # 可选，自定义系统提示词

[provider]
name = "openai"
model = "gpt-4.1"

[[mcp_servers]]
name = "filesystem"
transport = "stdio"
command = "python"
args = ["server.py"]
cwd = "D:/tools/mcp-filesystem"
enabled = true

[mcp_servers.unityMCP]
transport = "http"
url = "http://192.168.3.161:8081/mcp"
http_headers = { "X-API-Key" = "replace-me", "Accept" = "text/event-stream" }
startup_timeout_sec = 20
enabled = true
```

### 配置系统提示词

OpenAgent 支持两种方式配置系统提示词：

#### 1. 使用默认模板（仅配置名称）

如果只配置 `agent.name`，系统会使用内置的默认提示词模板：

```toml
[agent]
name = "MyAgent"
```

默认模板会自动将 `{name}` 替换为你配置的名称，生成如下提示词：

```
You are MyAgent, a top-rated AI assistant.
You are exceptionally strong at coding tasks, software design, debugging, implementation, and complex reasoning.
You solve problems with clear, defensible thinking, strong technical judgment, and careful tool use.
Be precise, pragmatic, and direct. Prefer concrete actions over vague advice.
When needed, inspect the workspace and use tools to verify assumptions before acting.
```

#### 2. 完全自定义系统提示词

通过 `system_prompt` 字段可以完全覆盖默认提示词：

```toml
[agent]
name = "CodeReviewer"
system_prompt = """你是一个专业的代码审查专家。

你的职责：
- 审查代码质量和安全性
- 提供改进建议
- 确保代码符合最佳实践

请始终保持专业和友好的态度。"""
```

运行时会根据角色添加额外信息：
- **Lead Agent**: 会添加工具使用指南、技能列表、工作空间路径等信息
- **Worker Agent**: 会添加协作协议、消息通信、空闲循环等信息

#### 3. 多行提示词配置

对于较长的系统提示词，可以使用 TOML 的多行字符串语法：

```toml
[agent]
name = "OpenAgent"
system_prompt = '''
你是一个专业的AI编程助手。

核心能力：
1. 代码编写与调试
2. 软件架构设计
3. 问题分析与解决

工作原则：
- 代码优先，避免空谈
- 注重可读性和可维护性
- 遵循项目既有规范
'''
```

或使用字面量字符串（保留换行）：

```toml
[agent]
name = "OpenAgent"
system_prompt = """
第一行内容
第二行内容
"""

## REPL Commands

- `/compact`
- `/tasks`
- `/team`
- `/inbox`
- `/mcp`
- `/bg`
- `/help`
- `/exit`

## Notes

- Data is stored under `.openagent/` in the workspace root.
- MCP tools are exposed with the local name format `mcp__<server>__<tool>`.
- MCP config supports both `[[mcp_servers]]` array style and `[mcp_servers.<name>]` table style.
- The OpenAI adapter uses the chat completions API shape so provider differences stay isolated in `providers/`.
