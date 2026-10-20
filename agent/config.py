"""Settings for the Fare Watch agent, read from environment variables.

The defaults suit a laptop; Docker and GitHub Actions override them with env vars, so the
same code runs everywhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_SECONDS = int(os.environ.get("FAREWATCH_SCAN_SECONDS", "15"))


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
