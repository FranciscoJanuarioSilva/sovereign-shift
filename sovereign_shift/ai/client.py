"""OpenAI-compatible JSON client with a disk cache, shared by every agent."""

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "sovereign_shift" / "prompts"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def load_env(path: Path = ROOT / ".env") -> None:
    # tiny .env reader, real env vars win
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.txt").read_text()


def _extract_json(text: str) -> dict:
    # models sometimes wrap json in a code fence
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return json.loads(fenced.group(1) if fenced else text)


class AIClient:
    def __init__(self, cache_dir: Path, agent: str = "translator") -> None:
        load_env()
        self.agent = agent
        self.base_url = os.environ.get(f"SOVEREIGN_AI_{agent.upper()}_BASE_URL") or os.environ.get("SOVEREIGN_AI_BASE_URL") or DEFAULT_BASE_URL
        self.model = os.environ.get(f"SOVEREIGN_AI_{agent.upper()}_MODEL") or os.environ.get("SOVEREIGN_AI_MODEL")
        self.api_key = os.environ.get("SOVEREIGN_AI_API_KEY")
        self.cache_dir = cache_dir / ".cache" / agent
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self.model and self.api_key)

    def why_disabled(self) -> str | None:
        if not self.api_key:
            return "SOVEREIGN_AI_API_KEY not set"
        if not self.model:
            return "SOVEREIGN_AI_MODEL not set"
        return None

    def info(self) -> dict:
        return {"base_url": self.base_url, "model": self.model, "enabled": self.enabled}

    def _call(self, system: str, user: str) -> str:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=60)
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    def complete(self, system: str, user: str, model: type[T]) -> T | None:
        """Cached call that returns a validated model, or None after one retry."""
        key = hashlib.sha256(json.dumps([self.model, system, user]).encode()).hexdigest()[:24]
        cached = self.cache_dir / f"{key}.json"
        if cached.exists():
            try:
                return model.model_validate(json.loads(cached.read_text()))
            except (ValidationError, json.JSONDecodeError):
                cached.unlink()
        if not self.enabled:
            return None
        for attempt in range(2):
            try:
                data = _extract_json(self._call(system, user))
                result = model.model_validate(data)
            except (ValidationError, json.JSONDecodeError) as error:
                print(f"[{self.agent}] invalid answer (attempt {attempt + 1}): {str(error)[:200]}", file=sys.stderr)
                continue
            except Exception as error:  # network, auth, rate limit: give up, fall back
                print(f"[{self.agent}] call failed: {type(error).__name__}: {str(error)[:200]}", file=sys.stderr)
                return None
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(data, indent=2))
            return result
        return None
