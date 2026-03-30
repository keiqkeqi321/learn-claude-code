from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completion, Completer
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import CompleteStyle

COMMAND_SPECS = [
    ("/compact", "Compact the current session context"),
    ("/tasks", "Show persistent tasks"),
    ("/team", "Show teammate roster and states"),
    ("/inbox", "Read the lead inbox"),
    ("/mcp", "Show configured MCP servers and tools"),
    ("/bg", "Show background jobs"),
    ("/help", "Show available REPL commands"),
    ("/exit", "Exit chat mode"),
]

IGNORED_DIR_NAMES = {
    ".git",
    ".openagent",
    "__pycache__",
    ".venv",
    "node_modules",
}

TOKEN_PATTERN = re.compile(r"(?:^|\s)([@/])([^\s]*)$")


@dataclass(slots=True)
class PathCandidate:
    relative_path: str
    basename: str
    kind: str


class OpenAgentCompleter(Completer):
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self._path_candidates: list[PathCandidate] = []
        self._last_scan_at = 0.0

    def get_completions(self, document, complete_event):
        token = self._current_token(document.text_before_cursor)
        if token is None:
            return
        symbol, query = token
        if symbol == "/":
            yield from self._command_completions(query)
            return
        if symbol == "@":
            yield from self._file_completions(query)

    def _current_token(self, text_before_cursor: str) -> tuple[str, str] | None:
        match = TOKEN_PATTERN.search(text_before_cursor)
        if not match:
            return None
        symbol, query = match.groups()
        if symbol == "/" and not text_before_cursor.lstrip().startswith("/"):
            return None
        return symbol, query

    def _command_completions(self, query: str):
        lowered = query.lower()
        for command, description in COMMAND_SPECS:
            command_name = command[1:]
            haystack = f"{command_name} {description}".lower()
            if lowered and lowered not in haystack:
                continue
            yield Completion(
                text=command_name,
                start_position=-len(query),
                display=command,
                display_meta=description,
            )

    def _file_completions(self, query: str):
        for candidate in self._matching_paths(query):
            insertion = candidate.relative_path
            if candidate.kind == "dir" and not insertion.endswith("/"):
                insertion += "/"
            yield Completion(
                text=insertion,
                start_position=-len(query),
                display=candidate.relative_path + ("/" if candidate.kind == "dir" and not candidate.relative_path.endswith("/") else ""),
                display_meta="folder" if candidate.kind == "dir" else "file",
            )

    def _matching_paths(self, query: str) -> list[PathCandidate]:
        self._refresh_paths()
        lowered = query.lower()
        if not lowered:
            return self._path_candidates[:30]

        def score(item: PathCandidate) -> tuple[int, int, int, str]:
            basename = item.basename.lower()
            path = item.relative_path.lower()
            basename_starts = 0 if basename.startswith(lowered) else 1
            basename_contains = 0 if lowered in basename else 1
            kind_rank = 0 if item.kind == "dir" else 1
            return (basename_starts, basename_contains, kind_rank, item.relative_path)

        matches = [
            candidate
            for candidate in self._path_candidates
            if lowered in candidate.relative_path.lower() or lowered in candidate.basename.lower()
        ]
        return sorted(matches, key=score)[:30]

    def _refresh_paths(self) -> None:
        now = time.time()
        if self._path_candidates and now - self._last_scan_at < 5:
            return
        candidates: list[PathCandidate] = []
        for path in self.workspace_root.rglob("*"):
            relative_parts = path.relative_to(self.workspace_root).parts
            if any(part in IGNORED_DIR_NAMES for part in relative_parts):
                continue
            if path.is_dir():
                kind = "dir"
            elif path.is_file():
                kind = "file"
            else:
                continue
            relative = path.relative_to(self.workspace_root).as_posix()
            candidates.append(PathCandidate(relative_path=relative, basename=path.name, kind=kind))
        self._path_candidates = sorted(
            candidates,
            key=lambda item: (0 if item.kind == "dir" else 1, len(item.relative_path), item.relative_path),
        )
        self._last_scan_at = now


def create_prompt_session(workspace_root: Path) -> PromptSession[str]:
    bindings = KeyBindings()

    @bindings.add("enter")
    def _handle_enter(event) -> None:
        buffer = event.current_buffer
        if buffer.complete_state:
            completion = buffer.complete_state.current_completion
            if completion is None and buffer.complete_state.completions:
                completion = buffer.complete_state.completions[0]
            if completion is not None:
                buffer.apply_completion(completion)
                return
        buffer.validate_and_handle()

    @bindings.add("escape")
    def _handle_escape(event) -> None:
        buffer = event.current_buffer
        if buffer.complete_state:
            buffer.cancel_completion()
            return

    return PromptSession(
        history=InMemoryHistory(),
        auto_suggest=AutoSuggestFromHistory(),
        completer=OpenAgentCompleter(workspace_root),
        complete_while_typing=True,
        reserve_space_for_menu=8,
        complete_style=CompleteStyle.MULTI_COLUMN,
        key_bindings=bindings,
    )
