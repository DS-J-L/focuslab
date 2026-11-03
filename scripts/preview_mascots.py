"""Preview the real overlay in isolation; optionally render a deterministic review image."""

import argparse
from pathlib import Path

from focuslab.ui.mascot.preview import run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--scale", type=float, choices=(1, 1.5, 2, 3), default=1)
    parser.add_argument("--state", choices=("focusing", "paused", "break"), default="focusing")
    parser.add_argument("--behavior")
    parser.add_argument("--at", type=float, default=0)
    args = parser.parse_args()
    return run(args.snapshot, args.scale, args.state, args.behavior, args.at)


if __name__ == "__main__":
    raise SystemExit(main())
