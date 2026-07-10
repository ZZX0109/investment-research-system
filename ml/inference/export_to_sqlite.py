from __future__ import annotations

import argparse
import json

from ml.inference.predict import infer
from ml.inference.retrieve_scenarios import retrieve


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="NVDA,TSLA,QQQ,XLE,600519,510300")
    parser.add_argument("--allow-synthetic", action="store_true")
    args = parser.parse_args()
    results = []
    for symbol in [item.strip().upper() for item in args.symbols.split(",") if item.strip()]:
        prediction = infer(symbol, allow_synthetic=args.allow_synthetic, write_sqlite=True)
        scenarios = retrieve(symbol, top_k=5, write_sqlite=True) if prediction.get("ok") else {"ok": False, "similarScenarios": []}
        results.append({"symbol": symbol, "prediction": prediction, "scenarios": scenarios})
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
