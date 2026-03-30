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
```

## REPL Commands

- `/compact`
- `/tasks`
- `/team`
- `/inbox`
- `/bg`
- `/help`
- `/exit`

## Notes

- Data is stored under `.openagent/` in the workspace root.
- MCP tools are exposed with the local name format `mcp__<server>__<tool>`.
- The OpenAI adapter uses the chat completions API shape so provider differences stay isolated in `providers/`.
