from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from investment_research.repository.sqlite import SQLiteUnitOfWork


ROOT = Path(__file__).resolve().parents[3]


class ResearchFindingsService:
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def model_findings(self) -> dict[str, object]:
        return self._read("audits/model_research_findings.json")

    def paper_summary(self, owner_user_id: UUID) -> dict[str, object]:
        historical = self._read("audits/paper_simulation.json")
        prospective = self.uow.agent_runtime.paper_summary(owner_user_id)
        return {"historical": historical, **prospective}

    @staticmethod
    def _read(relative: str) -> dict[str, object]:
        path = ROOT / relative
        if not path.exists():
            return {"status": "not_generated", "path": relative}
        return json.loads(path.read_text(encoding="utf-8"))
