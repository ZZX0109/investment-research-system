from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from investment_research.domain.base import Provenance, utc_now
from investment_research.domain.catalog import DataModePolicySummary
from investment_research.domain.enums import DataMode, DataSourceType


@dataclass(frozen=True)
class DataModePolicy:
    data_mode: DataMode
    allowed_source_types: tuple[DataSourceType, ...]
    description: str
    judge_gate_reason: str | None = None


class DataModePolicyService:
    def __init__(self) -> None:
        self._policies = {
            DataMode.DEMO: DataModePolicy(
                data_mode=DataMode.DEMO,
                allowed_source_types=(
                    DataSourceType.SYNTHETIC,
                    DataSourceType.BACKFILLED,
                    DataSourceType.MANUAL_OVERRIDE,
                ),
                description="Stable presentation mode backed by fixed synthetic and backfilled records.",
                judge_gate_reason="Demo mode is presentation-only and should not produce live investment advice.",
            ),
            DataMode.SANDBOX: DataModePolicy(
                data_mode=DataMode.SANDBOX,
                allowed_source_types=(
                    DataSourceType.SYNTHETIC,
                    DataSourceType.BACKFILLED,
                    DataSourceType.MANUAL_OVERRIDE,
                ),
                description="Synthetic experimentation mode for testing, training, and regression coverage.",
                judge_gate_reason="Sandbox mode is intended for testing and training, not real-money recommendations.",
            ),
            DataMode.REAL: DataModePolicy(
                data_mode=DataMode.REAL,
                allowed_source_types=(
                    DataSourceType.REAL,
                    DataSourceType.BACKFILLED,
                    DataSourceType.MANUAL_OVERRIDE,
                ),
                description="User-facing mode for real-market workflows with traceable live or operator-managed inputs.",
            ),
        }

    def describe_modes(self) -> list[DataModePolicySummary]:
        return [
            DataModePolicySummary(
                data_mode=policy.data_mode.value,
                allowed_source_types=[source.value for source in policy.allowed_source_types],
                description=policy.description,
                judge_gate_reason=policy.judge_gate_reason,
            )
            for policy in self._policies.values()
        ]

    def get_policy(self, data_mode: DataMode) -> DataModePolicy:
        return self._policies[data_mode]

    def validate_source_type(self, *, data_mode: DataMode, source_type: DataSourceType) -> None:
        policy = self.get_policy(data_mode)
        if source_type not in policy.allowed_source_types:
            allowed = ", ".join(source.value for source in policy.allowed_source_types)
            raise ValueError(
                f"Source type '{source_type.value}' is not allowed in {data_mode.value} mode. Allowed: {allowed}."
            )

    def build_provenance(
        self,
        *,
        data_mode: DataMode,
        source_type: DataSourceType,
        source_name: str,
        observed_at: datetime,
        confidence: float,
    ) -> Provenance:
        self.validate_source_type(data_mode=data_mode, source_type=source_type)
        return Provenance(
            data_mode=data_mode,
            source_type=source_type,
            source_name=source_name,
            observed_at=observed_at,
            confidence=confidence,
        )

    def build_manual_provenance(
        self,
        *,
        data_mode: DataMode,
        source_name: str,
        observed_at: datetime | None = None,
        confidence: float = 1.0,
    ) -> Provenance:
        return self.build_provenance(
            data_mode=data_mode,
            source_type=DataSourceType.MANUAL_OVERRIDE,
            source_name=source_name,
            observed_at=observed_at or utc_now(),
            confidence=confidence,
        )

    def build_audit_provenance(self, *, data_mode: DataMode, observed_at: datetime | None = None) -> Provenance:
        return self.build_manual_provenance(
            data_mode=data_mode,
            source_name=f"audit-log:{data_mode.value}",
            observed_at=observed_at,
            confidence=1.0,
        )

    def ensure_uniform_mode(self, *, data_modes: list[DataMode], label: str) -> DataMode:
        if not data_modes:
            return DataMode.REAL
        distinct_modes = sorted({mode.value for mode in data_modes})
        if len(distinct_modes) > 1:
            raise ValueError(
                f"{label} cannot mix data modes transparently. Received: {', '.join(distinct_modes)}."
            )
        return data_modes[0]

    def build_judge_mode_gates(self, data_modes: list[str]) -> list[str]:
        gates: list[str] = []
        for mode_name in sorted(set(data_modes)):
            mode = DataMode(mode_name)
            policy = self.get_policy(mode)
            if policy.judge_gate_reason:
                gates.append(policy.judge_gate_reason)
        return gates
