from __future__ import annotations

from pathlib import Path

from investment_research.training.models import ModelCard, TrainingExperimentReport


class TrainingArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def write_experiment_report(self, report: TrainingExperimentReport, *, name: str) -> Path:
        path = self.root / f"{name}-experiment.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return path

    def write_model_card(self, card: ModelCard, *, name: str) -> Path:
        path = self.root / f"{name}-model-card.json"
        path.write_text(card.model_dump_json(indent=2), encoding="utf-8")
        return path
