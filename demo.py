"""Launch a local game: tracker plus N trainers. Ctrl-C stops everything.

Usage:
    python demo.py [--tracker-port 5009] [--trainers 2] [--base-port 5010]

Then open http://127.0.0.1:5010 (and :5011, ...) in a browser.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build_commands(tracker_port, trainer_ports):
    """Return [(argv, label)] for the tracker and each trainer process."""
    commands = [
        (
            [sys.executable, str(ROOT / "nodetracker.py"), str(tracker_port)],
            f"tracker :{tracker_port}",
        )
    ]
    for port in trainer_ports:
        commands.append(
            (
                [sys.executable, str(ROOT / "app.py"), str(tracker_port), str(port)],
                f"trainer :{port}",
            )
        )
    return commands


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a local Pokemon trading game")
    parser.add_argument("--tracker-port", type=int, default=5009)
    parser.add_argument("--trainers", type=int, default=2)
    parser.add_argument("--base-port", type=int, default=5010)
    args = parser.parse_args(argv)
    if args.trainers < 1:
        parser.error("--trainers must be at least 1")
    trainer_ports = list(range(args.base_port, args.base_port + args.trainers))
    procs = []
    try:
        for cmd, label in build_commands(args.tracker_port, trainer_ports):
            proc = subprocess.Popen(cmd, cwd=ROOT)
            procs.append((proc, label))
            print(f"started {label} (pid {proc.pid})", flush=True)
        print(
            f"Open http://127.0.0.1:{trainer_ports[0]} in your browser",
            flush=True,
        )
        while True:
            for proc, label in procs:
                if proc.poll() is not None:
                    print(f"{label} exited ({proc.returncode}); stopping", flush=True)
                    return 1
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopping", flush=True)
        return 0
    finally:
        for proc, _ in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc, _ in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
