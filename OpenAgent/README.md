# OpenAgent

OpenAgent is a modular AI agent CLI that ports the feature set of `agents/s_full.py` into a reusable project layout. It keeps the original loop-and-tools interaction model while adding clearer layering for providers, storage, MCP integration, and teammate orchestration.

## Included in this MVP

- Interactive CLI with chat, run, tasks, compact, and doctor flows
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
- MCP client integration over `stdio` and HTTP
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
python -m openagent doctor
```

4. Start interactive chat:

```bash
python -m openagent
```

You can also resume a previous session through the picker:

```bash
python -m openagent -r
```

If you install the console entrypoint, the same commands work as:

```bash
openagent
openagent -r
```

## Configuration

OpenAgent reads configuration from:

1. `.env` in the workspace root
2. process environment variables
3. `openagent.toml` in the workspace root

`openagent.toml` is optional. Missing values fall back to defaults from `openagent/config/settings.py`.

### Environment Variables

Provider-related environment variables:

- `OPENAGENT_PROVIDER`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `MODEL_ID`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `OPENAI_ORG`

### openagent.toml

Supported top-level sections:

- `[agent]`
- `[provider]`
- `[runtime]`
- `[[mcp_servers]]` or `[mcp_servers.<name>]`

Example:

```toml
[agent]
name = "OpenAgent"
# Optional: fully override the built-in base system prompt.
# system_prompt = """
# You are a careful coding agent.
# """

[provider]
name = "anthropic" # or "openai"
model = "claude-sonnet-4-5"
# base_url = "https://api.anthropic.com"
# max_tokens = 8000
# timeout_seconds = 120

[runtime]
token_threshold = 100000
command_timeout_seconds = 120
background_poll_interval_seconds = 2
teammate_idle_timeout_seconds = 60
teammate_poll_interval_seconds = 5
max_tool_output_chars = 50000
max_subagent_rounds = 30
max_agent_rounds = 50

[[mcp_servers]]
name = "filesystem"
transport = "stdio"
command = "python"
args = ["server.py"]
cwd = "D:/tools/mcp-filesystem"
enabled = false
timeout_seconds = 30
protocol_version = "2025-11-25"

[mcp_servers.unityMCP]
transport = "http"
url = "http://127.0.0.1:8081/mcp"
http_headers = { "X-API-Key" = "replace-me", "Accept" = "text/event-stream" }
startup_timeout_sec = 20
enabled = false
```

### Agent Prompt Configuration

If you set only `agent.name`, OpenAgent uses the built-in default base prompt and injects the configured name into it.

```toml
[agent]
name = "MyAgent"
```

If you set `agent.system_prompt`, that string replaces the built-in base prompt.

```toml
[agent]
name = "CodeReviewer"
system_prompt = """
You are a code review specialist.
Prioritize correctness, regressions, and missing tests.
"""
```

At runtime, OpenAgent also appends role-specific guidance to the base prompt, including:

- current workspace path
- available skills
- tool usage guidance
- current execution environment

The execution environment block tells the model which OS it is running on and how to use the `bash` tool correctly:

- on Unix-like systems, `bash` uses the system shell
- on Windows, `bash` runs PowerShell-compatible commands

That means Windows sessions should prefer commands such as:

- `Get-ChildItem`
- `Get-Content`
- `Select-String`
- `Select-Object`

### MCP Server Configuration

OpenAgent supports both styles below.

Array style:

```toml
[[mcp_servers]]
name = "filesystem"
transport = "stdio"
command = "python"
args = ["server.py"]
cwd = "D:/tools/mcp-filesystem"
enabled = true
```

Named table style:

```toml
[mcp_servers.unityMCP]
transport = "http"
url = "http://127.0.0.1:8081/mcp"
http_headers = { "X-API-Key" = "replace-me", "Accept" = "text/event-stream" }
startup_timeout_sec = 20
enabled = true
```

Supported MCP fields include:

- `transport`
- `url`
- `command`
- `args`
- `cwd`
- `env`
- `http_headers`
- `enabled`
- `timeout_seconds` or `request_timeout_sec`
- `startup_timeout_sec`
- `protocol_version`

## REPL Commands

- `/compact`
- `/tasks`
- `/team`
- `/inbox`
- `/mcp`
- `/toollog`
- `/bg`
- `/help`
- `/exit`

## Notes

- Data is stored under `.openagent/` in the workspace root.
- MCP tools are exposed with the local name format `mcp__<server>__<tool>`.
- MCP config supports both `[[mcp_servers]]` array style and `[mcp_servers.<name>]` table style.
- The OpenAI adapter uses the chat completions API shape so provider differences stay isolated in `providers/`.
