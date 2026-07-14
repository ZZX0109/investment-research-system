from __future__ import annotations

import json
from pathlib import Path

from investment_research.training.models import (
    ModelCard,
    ModelStatus,
    PromotionGatePolicy,
    PromotionGateResult,
    RegistryState,
    TrainingExperimentAuditSummary,
)
from investment_research.training.promotion import evaluate_promotion_gate


class TrainingRegistryService:
    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

    def list_models(self, *, task_name: str | None = None) -> list[ModelCard]:
        state = self._read_state()
        if task_name is None:
            return state.models
        return [model for model in state.models if model.task_name == task_name]

    def register_candidate(self, card: ModelCard) -> ModelCard:
        state = self._read_state()
        state.models = [model for model in state.models if model.model_id != card.model_id]
        state.models.append(card.model_copy(update={"status": ModelStatus.CANDIDATE}))
        self._write_state(state)
        return card

    def get_active_model(self, task_name: str) -> ModelCard | None:
        approved = [model for model in self._read_state().models if model.task_name == task_name and model.status == ModelStatus.APPROVED]
        if not approved:
            return None
        return sorted(approved, key=lambda item: item.approved_at or item.training_created_at, reverse=True)[0]

    def approve_model(self, model_id: str) -> ModelCard:
        state = self._read_state()
        approved_card: ModelCard | None = None
        updated: list[ModelCard] = []
        for card in state.models:
            if card.model_id == model_id:
                approved_card = card.model_copy(update={"status": ModelStatus.APPROVED})
                updated.append(approved_card)
            else:
                updated.append(card)
        if approved_card is None:
            raise ValueError("Model card not found")

        final_models: list[ModelCard] = []
        for card in updated:
            if card.task_name == approved_card.task_name and card.model_id != approved_card.model_id and card.status == ModelStatus.APPROVED:
                final_models.append(card.model_copy(update={"status": ModelStatus.ROLLED_BACK, "replaced_by": approved_card.model_id}))
            else:
                final_models.append(card)
        state.models = final_models
        self._write_state(state)
        return approved_card

    def approve_model_if_eligible(
        self,
        model_id: str,
        *,
        baseline_model_id: str | None = None,
        policy: PromotionGatePolicy | None = None,
        audit: TrainingExperimentAuditSummary | None = None,
    ) -> PromotionGateResult:
        state = self._read_state()
        candidate = next((card for card in state.models if card.model_id == model_id), None)
        if candidate is None:
            raise ValueError("Model card not found")
        baseline = None if baseline_model_id is None else next((card for card in state.models if card.model_id == baseline_model_id), None)
        if baseline_model_id is not None and baseline is None:
            raise ValueError("Baseline model card not found")

        result = evaluate_promotion_gate(candidate=candidate, baseline=baseline, policy=policy, audit=audit)
        if not result.eligible:
            rewritten = [
                (
                    card.model_copy(update={"notes": [*card.notes, *result.reasons]})
                    if card.model_id == model_id
                    else card
                )
                for card in state.models
            ]
            state.models = rewritten
            self._write_state(state)
            return result

        self.approve_model(model_id)
        return result

    def reject_model(self, model_id: str, *, reason: str) -> ModelCard:
        state = self._read_state()
        rejected: ModelCard | None = None
        state.models = [
            (
                card.model_copy(update={"status": ModelStatus.REJECTED, "notes": [*card.notes, reason]})
                if card.model_id == model_id
                else card
            )
            for card in state.models
        ]
        for card in state.models:
            if card.model_id == model_id:
                rejected = card
                break
        if rejected is None:
            raise ValueError("Model card not found")
        self._write_state(state)
        return rejected

    def rollback_model(self, model_id: str) -> ModelCard:
        state = self._read_state()
        target = next((card for card in state.models if card.model_id == model_id), None)
        if target is None:
            raise ValueError("Model card not found")
        if target.status != ModelStatus.APPROVED:
            raise ValueError("Only approved models can be rolled back")

        previous = next(
            (
                card
                for card in sorted(state.models, key=lambda item: item.training_created_at, reverse=True)
                if card.task_name == target.task_name and card.model_id != target.model_id and card.status in {ModelStatus.ROLLED_BACK, ModelStatus.CANDIDATE}
            ),
            None,
        )
        if previous is None:
            raise ValueError("No previous model is available to restore")

        rewritten: list[ModelCard] = []
        restored: ModelCard | None = None
        for card in state.models:
            if card.model_id == target.model_id:
                rewritten.append(card.model_copy(update={"status": ModelStatus.ROLLED_BACK}))
            elif card.model_id == previous.model_id:
                restored = card.model_copy(update={"status": ModelStatus.APPROVED, "replaced_by": None})
                rewritten.append(restored)
            else:
                rewritten.append(card)
        state.models = rewritten
        self._write_state(state)
        assert restored is not None
        return restored

    def _read_state(self) -> RegistryState:
        if not self.registry_path.exists():
            return RegistryState()
        return RegistryState.model_validate_json(self.registry_path.read_text(encoding="utf-8"))

    def _write_state(self, state: RegistryState) -> None:
        self.registry_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
