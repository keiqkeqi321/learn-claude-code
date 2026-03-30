from __future__ import annotations

import re
from pathlib import Path


class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        self.skills = {}
        if not self.skills_dir.exists():
            return
        for path in sorted(self.skills_dir.rglob("SKILL.md")):
            text = path.read_text(encoding="utf-8")
            meta, body = self._parse(text)
            name = meta.get("name", path.parent.name)
            self.skills[name] = {
                "name": name,
                "meta": meta,
                "body": body,
                "path": path,
            }

    def _parse(self, text: str) -> tuple[dict[str, str], str]:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text.strip()
        meta: dict[str, str] = {}
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
        return meta, match.group(2).strip()

    def descriptions(self) -> str:
        if not self.skills:
            return "(no skills)"
        return "\n".join(
            f"- {name}: {skill['meta'].get('description', '-')}" for name, skill in self.skills.items()
        )

    def load(self, name: str) -> str:
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(sorted(self.skills))
            return f"Error: Unknown skill '{name}'. Available: {available}"
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"
