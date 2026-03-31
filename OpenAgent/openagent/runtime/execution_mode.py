from __future__ import annotations

from dataclasses import dataclass

DEFAULT_EXECUTION_MODE = "accept_edits"
AUTHORIZATION_TOOL_NAME = "request_authorization"
MODE_SWITCH_TOOL_NAME = "request_mode_switch"
EXECUTION_MODE_ORDER = ("shortcuts", "plan", "accept_edits", "yolo")
NON_YOLO_EXECUTION_MODES = ("shortcuts", "plan", "accept_edits")
READ_ONLY_TOOL_NAMES = frozenset(
    {
        "read_file",
        "load_skill",
        "compress",
        AUTHORIZATION_TOOL_NAME,
        MODE_SWITCH_TOOL_NAME,
        "TodoWrite",
        "task_get",
        "task_list",
        "list_teammates",
        "check_background",
    }
)
FILE_EDIT_TOOL_NAMES = frozenset({"write_file", "edit_file"})


@dataclass(frozen=True, slots=True)
class ExecutionModeSpec:
    key: str
    badge: str
    label: str
    color: str
    ansi_color: str
    guidance: str

    @property
    def title(self) -> str:
        return f"{self.badge} {self.label}"


SHORTCUTS_BADGE = "?"
PLAN_BADGE = "\u23f8"
ACCEPT_EDITS_BADGE = "\u23f5\u23f5"
YOLO_BADGE = "!"


EXECUTION_MODES: dict[str, ExecutionModeSpec] = {
    "shortcuts": ExecutionModeSpec(
        key="shortcuts",
        badge=SHORTCUTS_BADGE,
        label="for shortcuts",
        color="fg:#94a3b8",
        ansi_color="\x1b[38;5;110m",
        guidance=(
            "Execution mode:\n"
            "- Current mode: ? for shortcuts.\n"
            "- Keep workspace files read-only.\n"
            "- Use lightweight, read-only tools only.\n"
            "- Call request_authorization before asking for edits or broader tool access.\n"
            "- Call request_mode_switch to ask the user to move to shortcuts, plan, or accept_edits when needed."
        ),
    ),
    "plan": ExecutionModeSpec(
        key="plan",
        badge=PLAN_BADGE,
        label="plan mode on",
        color="fg:#22d3ee bold",
        ansi_color="\x1b[38;5;51m",
        guidance=(
            "Execution mode:\n"
            "- Current mode: \u23f8 plan mode on.\n"
            "- Keep workspace files read-only.\n"
            "- Inspect context with read-only tools when needed.\n"
            "- Return a concrete implementation plan before asking for a higher-permission mode.\n"
            "- If execution is needed after planning, call request_mode_switch or request_authorization first."
        ),
    ),
    "accept_edits": ExecutionModeSpec(
        key="accept_edits",
        badge=ACCEPT_EDITS_BADGE,
        label="accept edits on",
        color="fg:#f59e0b bold",
        ansi_color="\x1b[38;5;214m",
        guidance=(
            "Execution mode:\n"
            "- Current mode: \u23f5\u23f5 accept edits on.\n"
            "- You may edit workspace files with write_file and edit_file.\n"
            "- Treat other tools as requiring explicit user approval.\n"
            "- Call request_authorization before using a blocked non-edit tool.\n"
            "- You may call request_mode_switch only for shortcuts, plan, or accept_edits."
        ),
    ),
    "yolo": ExecutionModeSpec(
        key="yolo",
        badge=YOLO_BADGE,
        label="Yolo",
        color="fg:#ef4444 bold",
        ansi_color="\x1b[38;5;196m",
        guidance=(
            "Execution mode:\n"
            "- Current mode: ! Yolo.\n"
            "- Full autonomy is enabled.\n"
            "- You may use tools as needed, but still avoid reckless or destructive actions."
        ),
    ),
}


def normalize_execution_mode(mode: str | None) -> str:
    key = str(mode or DEFAULT_EXECUTION_MODE).strip().lower()
    return key if key in EXECUTION_MODES else DEFAULT_EXECUTION_MODE


def execution_mode_spec(mode: str | None) -> ExecutionModeSpec:
    return EXECUTION_MODES[normalize_execution_mode(mode)]


def next_execution_mode(mode: str | None) -> str:
    current = normalize_execution_mode(mode)
    index = EXECUTION_MODE_ORDER.index(current)
    return EXECUTION_MODE_ORDER[(index + 1) % len(EXECUTION_MODE_ORDER)]


def execution_mode_status_text(mode: str | None) -> str:
    return f"{execution_mode_spec(mode).title}  (Shift+Tab to cycle)"


def tool_block_message(mode: str | None, tool_name: str) -> str | None:
    spec = execution_mode_spec(mode)
    if spec.key == "yolo":
        return None
    if tool_name in {AUTHORIZATION_TOOL_NAME, MODE_SWITCH_TOOL_NAME}:
        return None
    if tool_name in READ_ONLY_TOOL_NAMES:
        return None
    if spec.key == "accept_edits" and tool_name in FILE_EDIT_TOOL_NAMES:
        return None
    if tool_name in FILE_EDIT_TOOL_NAMES:
        return (
            f"Blocked in {spec.title}: workspace files are read-only. "
            f"Call request_authorization or request_mode_switch to {ACCEPT_EDITS_BADGE} accept edits on."
        )
    return (
        f"Blocked in {spec.title}: '{tool_name}' requires broader tool access. "
        "Call request_authorization if this tool is necessary."
        if spec.key != "accept_edits"
        else (
            f"Blocked in {spec.title}: '{tool_name}' still requires explicit user approval. "
            "Call request_authorization if this tool is necessary."
        )
    )
