from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_research.service.legacy_inventory import build_inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/legacy_four_market_public_data.inventory.json"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    inventory = build_inventory(
        root,
        [root / "data/free_research_raw", root / "data/free_research_standard"],
    )
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
