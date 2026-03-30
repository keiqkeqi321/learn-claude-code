from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv

from openagent.config.models import (
    AppSettings,
    MCPServerSettings,
    ProviderSettings,
    RuntimeSettings,
    StorageSettings,
)


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _resolve_optional_path(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (root / path).resolve()


def _build_mcp_server(root: Path, name: str, item: dict) -> MCPServerSettings:
    transport = str(item.get("transport", "http" if item.get("url") else "stdio")).lower()
    return MCPServerSettings(
        name=name,
        transport=transport,
        url=str(item["url"]) if item.get("url") else None,
        command=str(item.get("command", "")),
        args=[str(arg) for arg in item.get("args", [])],
        cwd=_resolve_optional_path(root, item.get("cwd")),
        env={str(k): str(v) for k, v in item.get("env", {}).items()},
        http_headers={str(k): str(v) for k, v in item.get("http_headers", {}).items()},
        enabled=bool(item.get("enabled", True)),
        timeout_seconds=int(item.get("timeout_seconds", item.get("request_timeout_sec", 30))),
        startup_timeout_seconds=int(item.get("startup_timeout_sec", item.get("timeout_seconds", 30))),
        protocol_version=str(item.get("protocol_version", "2025-11-25")),
    )


def _load_mcp_servers(root: Path, raw: dict) -> list[MCPServerSettings]:
    mcp_servers: list[MCPServerSettings] = []
    servers_raw = raw.get("mcp_servers", {})
    if isinstance(servers_raw, list):
        for item in servers_raw:
            if not isinstance(item, dict) or "name" not in item:
                continue
            mcp_servers.append(_build_mcp_server(root, str(item["name"]), item))
        return mcp_servers
    if isinstance(servers_raw, dict):
        for name, item in servers_raw.items():
            if not isinstance(item, dict):
                continue
            mcp_servers.append(_build_mcp_server(root, str(name), item))
    return mcp_servers


def _storage_settings(workspace_root: Path) -> StorageSettings:
    data_dir = workspace_root / ".openagent"
    return StorageSettings(
        data_dir=data_dir,
        transcripts_dir=data_dir / "transcripts",
        sessions_dir=data_dir / "sessions",
        tasks_dir=data_dir / "tasks",
        inbox_dir=data_dir / "inbox",
        team_dir=data_dir / "team",
        jobs_dir=data_dir / "jobs",
        requests_dir=data_dir / "requests",
        logs_dir=data_dir / "logs",
    )


def load_settings(workspace_root: str | Path | None = None) -> AppSettings:
    root = Path(workspace_root or Path.cwd()).resolve()
    load_dotenv(root / ".env", override=False)
    load_dotenv(override=False)
    config_path = root / "openagent.toml"
    raw = _read_toml(config_path)

    provider_raw = raw.get("provider", {})
    provider_name = str(provider_raw.get("name", os.getenv("OPENAGENT_PROVIDER", "anthropic"))).strip().lower()
    if provider_name == "openai":
        provider = ProviderSettings(
            name="openai",
            model=str(provider_raw.get("model", os.getenv("OPENAI_MODEL", "gpt-4.1"))),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=str(provider_raw.get("base_url", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))),
            organization=os.getenv("OPENAI_ORG") or provider_raw.get("organization"),
            max_tokens=int(provider_raw.get("max_tokens", 8_000)),
            timeout_seconds=int(provider_raw.get("timeout_seconds", 120)),
        )
    else:
        provider = ProviderSettings(
            name="anthropic",
            model=str(provider_raw.get("model", os.getenv("MODEL_ID", "claude-sonnet-4-5"))),
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            base_url=os.getenv("ANTHROPIC_BASE_URL") or provider_raw.get("base_url"),
            max_tokens=int(provider_raw.get("max_tokens", 8_000)),
            timeout_seconds=int(provider_raw.get("timeout_seconds", 120)),
        )

    runtime_raw = raw.get("runtime", {})
    runtime = RuntimeSettings(
        token_threshold=int(runtime_raw.get("token_threshold", 100_000)),
        command_timeout_seconds=int(runtime_raw.get("command_timeout_seconds", 120)),
        background_poll_interval_seconds=int(runtime_raw.get("background_poll_interval_seconds", 2)),
        teammate_idle_timeout_seconds=int(runtime_raw.get("teammate_idle_timeout_seconds", 60)),
        teammate_poll_interval_seconds=int(runtime_raw.get("teammate_poll_interval_seconds", 5)),
        max_tool_output_chars=int(runtime_raw.get("max_tool_output_chars", 50_000)),
        max_subagent_rounds=int(runtime_raw.get("max_subagent_rounds", 30)),
        max_agent_rounds=int(runtime_raw.get("max_agent_rounds", 50)),
    )

    mcp_servers = _load_mcp_servers(root, raw)

    settings = AppSettings(
        workspace_root=root,
        provider=provider,
        runtime=runtime,
        storage=_storage_settings(root),
        mcp_servers=mcp_servers,
        raw_config=raw,
    )
    ensure_storage_dirs(settings)
    return settings


def ensure_storage_dirs(settings: AppSettings) -> None:
    for path in (
        settings.storage.data_dir,
        settings.storage.transcripts_dir,
        settings.storage.sessions_dir,
        settings.storage.tasks_dir,
        settings.storage.inbox_dir,
        settings.storage.team_dir,
        settings.storage.jobs_dir,
        settings.storage.requests_dir,
        settings.storage.logs_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
