import sys
from pathlib import Path

from demo import ROOT, build_commands


def test_build_commands_tracker_plus_trainers():
    commands = build_commands(5009, [5010, 5011])
    assert [label for _, label in commands] == [
        "tracker :5009",
        "trainer :5010",
        "trainer :5011",
    ]
    tracker, first, second = [cmd for cmd, _ in commands]
    assert tracker == [sys.executable, str(ROOT / "nodetracker.py"), "5009"]
    assert first == [sys.executable, str(ROOT / "app.py"), "5009", "5010"]
    assert second == [sys.executable, str(ROOT / "app.py"), "5009", "5011"]
    assert ROOT.is_dir()
    assert Path(ROOT / "nodetracker.py").exists()
    assert Path(ROOT / "app.py").exists()
