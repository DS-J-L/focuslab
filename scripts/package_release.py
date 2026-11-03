"""Package a verified folder build for full and incremental release clients."""

import argparse
from pathlib import Path

from focuslab.update_manifest import package

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("dist/FocusLab"))
    parser.add_argument("--output", type=Path, default=Path("dist/release"))
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    for asset in package(args.source, args.output, args.version):
        print(asset)
