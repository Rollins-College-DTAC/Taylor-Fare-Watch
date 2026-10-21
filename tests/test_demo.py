import subprocess
import sys
from datetime import datetime

from dashboard.demo import LocalDemo, demo_commands, demo_env


def test_agent_outlives_the_generator_by_a_minute():
    commands = demo_commands(30, python="py")
    assert commands["generator"] == ["py", "-m", "generator.generate", "--minutes", "30"]
    assert commands["agent"] == ["py", "-m", "agent.main", "--minutes", "31"]


def test_kill_switch_is_passed_to_both_processes_as_an_override():
    assert demo_env(True, base={"PATH": "x"}) == {"PATH": "x", "FAREWATCH_KILL_SWITCH": "1"}
    assert demo_env(False, base={"FAREWATCH_KILL_SWITCH": "1"})["FAREWATCH_KILL_SWITCH"] == "0"


def test_stop_ends_a_running_demo():
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    demo = LocalDemo({"generator": sleeper}, ends_at=datetime.now(), kill_switch=True, logs={})
    assert demo.running()
    demo.stop()
    sleeper.wait(timeout=10)
    assert not demo.running()
