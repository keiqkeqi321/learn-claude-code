from __future__ import annotations

from pathlib import Path

from openagent.storage.common import read_json, write_json


class TeamStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "team.json"

    def load(self) -> dict:
        return read_json(self.path, {"team_name": "default", "members": []})

    def save(self, payload: dict) -> None:
        write_json(self.path, payload)
