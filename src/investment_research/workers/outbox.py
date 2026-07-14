"""Run one bounded outbox delivery pass."""

from __future__ import annotations

import json

from investment_research.bootstrap.container import build_outbox_service, open_unit_of_work


def main() -> int:
    uow = open_unit_of_work()
    try:
        print(json.dumps(build_outbox_service(uow).drain(), ensure_ascii=False))
        return 0
    finally:
        uow.close()


if __name__ == "__main__":
    raise SystemExit(main())
