"""Settings for the Fare Watch agent, read from environment variables.

The defaults suit a laptop; Docker and GitHub Actions override them with env vars, so the
same code runs everywhere.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")  # local runs only; the cloud injects real env vars instead
SCAN_SECONDS = int(os.environ.get("FAREWATCH_SCAN_SECONDS", "15"))
PROMPTS_DIR = PROJECT_ROOT / "prompts"


def _path(env_var: str, default: Path) -> Path:
    return Path(os.environ.get(env_var, default))


@dataclass(frozen=True)
class Paths:
    inbox: Path
    processed: Path
    quarantine: Path
    data_dir: Path

    @property
    def sqlite(self) -> Path:
        return self.data_dir / "analytics.sqlite"

    @property
    def raw_json(self) -> Path:
        return self.data_dir / "raw.json"

    @classmethod
    def under(cls, root: Path) -> "Paths":
        """All folders inside one root, for tests and throwaway demo runs."""
        return cls(root / "inbox", root / "processed", root / "quarantine", root / "data")


def load_paths() -> Paths:
    return Paths(
        inbox=_path("FAREWATCH_INBOX", PROJECT_ROOT / "inbox"),
        processed=_path("FAREWATCH_PROCESSED", PROJECT_ROOT / "processed"),
        quarantine=_path("FAREWATCH_QUARANTINE", PROJECT_ROOT / "quarantine"),
        data_dir=_path("FAREWATCH_DATA", PROJECT_ROOT / "data"),
    )


def _flag(env_var: str, default: bool) -> bool:
    value = os.environ.get(env_var)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def anthropic_client_kwargs() -> dict:
    """Extra kwargs for Anthropic(...): some class Console keys are not scoped to a single
    workspace and need an explicit anthropic-workspace-id header on every request. Find the
    ID on the Console's workspace settings page and put it in .env as ANTHROPIC_WORKSPACE_ID."""
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    return {"default_headers": {"anthropic-workspace-id": workspace_id}} if workspace_id else {}


@dataclass(frozen=True)
class Settings:
    extract_model: str
    escalate_model: str
    jev_enabled: bool
    extract_prompt: str
    jev_questions: str
    kill_switch: bool
    max_tokens_per_run: int
    max_tokens_per_day: int
    category_confidence_min: float
    mxn_per_usd: float
    departure_year: int
    departure_month: int


def load_settings(path: Path | None = None) -> Settings:
    """config.toml, with FAREWATCH_KILL_SWITCH and FAREWATCH_JEV_ENABLED env overrides."""
    path = path or Path(os.environ.get("FAREWATCH_CONFIG", PROJECT_ROOT / "config.toml"))
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    models, prompts, limits, ref = cfg["models"], cfg["prompts"], cfg["limits"], cfg["reference"]
    return Settings(
        extract_model=models["extract"],
        escalate_model=models["escalate"],
        jev_enabled=_flag("FAREWATCH_JEV_ENABLED", models["jev_enabled"]),
        extract_prompt=prompts["extract"],
        jev_questions=prompts["jev_questions"],
        kill_switch=_flag("FAREWATCH_KILL_SWITCH", limits["kill_switch"]),
        max_tokens_per_run=limits["max_tokens_per_run"],
        max_tokens_per_day=limits["max_tokens_per_day"],
        category_confidence_min=limits["category_confidence_min"],
        mxn_per_usd=ref["mxn_per_usd"],
        departure_year=ref["departure_year"],
        departure_month=ref["departure_month"],
    )
