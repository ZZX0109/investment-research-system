from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from investment_research.domain.base import GenerationLink, Provenance
from investment_research.domain.enums import DataMode, DataSourceType, EvidenceType
from investment_research.domain.models import Asset, Evidence


def build_provenance() -> Provenance:
    return Provenance(
        data_mode=DataMode.DEMO,
        source_type=DataSourceType.SYNTHETIC,
        source_name="test-fixture",
        observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        confidence=0.8,
    )


def test_asset_requires_provenance_and_versions() -> None:
    asset = Asset(
        ticker="MSFT",
        name="Microsoft",
        asset_type="equity",
        provenance=build_provenance(),
    )

    assert asset.provenance.source_type == DataSourceType.SYNTHETIC
    assert asset.version.schema_version == "1.0.0"
    assert asset.version.entity_version == 1


def test_domain_entity_contract_exposes_schema_and_source() -> None:
    asset = Asset(
        ticker="AAPL",
        name="Apple",
        asset_type="equity",
        provenance=build_provenance(),
    )

    assert asset.schema == "1.0.0"
    assert asset.source == DataSourceType.SYNTHETIC


def test_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name="live-feed",
            observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
            confidence=1.5,
        )


def test_evidence_tracks_asset_and_source_metadata() -> None:
    asset = Asset(
        ticker="AAPL",
        name="Apple",
        asset_type="equity",
        provenance=build_provenance(),
    )
    evidence = Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.NEWS,
        title="Supply chain update",
        summary="Example evidence attached to the asset.",
        collected_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        provenance=build_provenance(),
    )

    assert evidence.asset_id == asset.id
    assert evidence.provenance.source_name == "test-fixture"


def test_evidence_supports_asset_refs_and_lineage_from_provenance() -> None:
    base = build_provenance()
    base.generation_chain = [
        GenerationLink(step="ingest", producer="test-producer", version="1.0.0"),
        GenerationLink(step="transform", producer="normalizer", version="1.0.1"),
    ]
    evidence = Evidence(
        asset_id=UUID("12345678-1234-1234-1234-123456789012"),
        evidence_type=EvidenceType.NEWS,
        title="Title",
        summary="Summary",
        collected_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        provenance=base,
    )

    assert str(evidence.asset_id) in [str(aid) for aid in evidence.asset_refs]
    assert evidence.lineage == base.generation_chain


def test_evidence_accepts_legacy_related_ids_input() -> None:
    legacy = Evidence.model_validate(
        {
            "asset_id": "12345678-1234-1234-1234-123456789012",
            "evidence_type": EvidenceType.RESEARCH_NOTE.value,
            "title": "Legacy",
            "summary": "legacy payload",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "related_ids": ["12345678-1234-1234-1234-123456789012"],
            "provenance": {
                "data_mode": DataMode.DEMO.value,
                "source_type": DataSourceType.SYNTHETIC.value,
                "source_name": "legacy-loader",
                "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                "confidence": 0.85,
            },
        }
    )

    assert str(legacy.asset_id) in {str(item) for item in legacy.asset_refs}
