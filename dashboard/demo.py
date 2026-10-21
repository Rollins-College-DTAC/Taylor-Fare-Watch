"""The local half of the sidebar's demo button: start the generator and the agent as
background processes for N minutes. Kept free of Streamlit so it can be unit tested.
(In the cloud the same button starts pipeline.yml instead; see dashboard/demo_panel.py.)
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from agent.config import PROJECT_ROOT, load_paths

DEMO_MINUTES = 30


def demo_commands(minutes: int, python: str = sys.executable) -> dict[str, list[str]]:
    """The agent runs one minute longer than the generator, so it picks up the last import."""
    return {
        "generator": [python, "-m", "generator.generate", "--minutes", str(minutes)],
        "agent": [python, "-m", "agent.main", "--minutes", str(minutes + 1)],
    }


def demo_env(kill_switch: bool, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env["FAREWATCH_KILL_SWITCH"] = "1" if kill_switch else "0"
    return env


@dataclass
class LocalDemo:
    processes: dict[str, subprocess.Popen]
    ends_at: datetime
    kill_switch: bool
    logs: dict[str, Path]

    def running(self) -> bool:
        return any(p.poll() is None for p in self.processes.values())

    def stop(self) -> None:
        for p in self.processes.values():
            if p.poll() is None:
                p.terminate()


def start_local_demo(minutes: int = DEMO_MINUTES, kill_switch: bool = False) -> LocalDemo:
    log_dir = load_paths().data_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    env = demo_env(kill_switch)
    processes, logs = {}, {}
    for name, command in demo_commands(minutes).items():
        logs[name] = log_dir / f"demo_{name}.log"
        with logs[name].open("w", encoding="utf-8") as log:  # the child keeps its own handle
            processes[name] = subprocess.Popen(
                command, cwd=PROJECT_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
    return LocalDemo(processes, datetime.now() + timedelta(minutes=minutes + 1), kill_switch, logs)
