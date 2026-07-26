"""Foreign-key-backed repositories for the long-lived research domain.

The legacy repositories remain compatibility projections. New relationships are
persisted here so a claim, run, gate, and source chain can be replayed without
parsing JSON payload columns.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from uuid import UUID, uuid4

from investment_research.domain.base import utc_now
from investment_research.domain.enums import AccessRole, ClaimStatus, JudgeVerdict
from investment_research.domain.long_term_models import Claim, GateEvaluation, GateFinding, ResourceShare
from investment_research.domain.models import AnalysisRun, Evidence, User
from investment_research.domain.models import ModelPrediction
from investment_research.domain.models import PortfolioRiskSnapshot


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


class RelationalDomainRepository:
    """Keeps canonical relations alongside compatibility records during cutover."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def is_registered_user(self, user_id: UUID) -> bool:
        """Return whether an authenticated user has a durable database row."""
        return self.connection.execute(
            "SELECT 1 FROM users WHERE id=?", (str(user_id),)
        ).fetchone() is not None

    def assign_owner(self, *, resource_type: str, resource_id: UUID, owner_user_id: UUID) -> None:
        existing = self.connection.execute(
            "SELECT owner_user_id FROM resource_owners WHERE resource_type=? AND resource_id=?",
            (resource_type, str(resource_id)),
        ).fetchone()
        if existing is not None:
            if str(existing[0]) != str(owner_user_id):
                raise ValueError("Resource owner is immutable")
            return
        self.connection.execute(
            "INSERT INTO resource_owners (id,resource_type,resource_id,owner_user_id,created_at) VALUES (?,?,?,?,?)",
            (str(uuid4()), resource_type, str(resource_id), str(owner_user_id), _iso(utc_now())),
        )
        self._commit()

    def assert_access(self, *, resource_type: str, resource_id: str, user_id: UUID, write: bool = False) -> None:
        row = self.connection.execute(
            "SELECT owner_user_id FROM resource_owners WHERE resource_type=? AND resource_id=?",
            (resource_type, resource_id),
        ).fetchone()
        if row is not None and str(row[0]) == str(user_id):
            return
        if not write:
            shared = self.connection.execute(
                "SELECT 1 FROM resource_shares WHERE resource_type=? AND resource_id=? AND viewer_user_id=? AND role='viewer'",
                (resource_type, resource_id, str(user_id)),
            ).fetchone()
            if shared is not None:
                return
        raise ValueError("Resource not found")

    def accessible_resource_ids(self, *, resource_type: str, user_id: UUID) -> set[str]:
        owned = self.connection.execute(
            "SELECT resource_id FROM resource_owners WHERE resource_type=? AND owner_user_id=?",
            (resource_type, str(user_id)),
        ).fetchall()
        shared = self.connection.execute(
            "SELECT resource_id FROM resource_shares WHERE resource_type=? AND viewer_user_id=? AND role='viewer'",
            (resource_type, str(user_id)),
        ).fetchall()
        return {str(row[0]) for row in [*owned, *shared]}

    def remove_resource_access(
        self,
        *,
        resource_type: str,
        resource_id: UUID,
        user_id: UUID,
    ) -> None:
        """Remove only one user's workspace link without touching other users or evidence."""
        self.assert_access(
            resource_type=resource_type,
            resource_id=str(resource_id),
            user_id=user_id,
            write=False,
        )
        self.connection.execute(
            "DELETE FROM resource_shares WHERE resource_type=? AND resource_id=? AND viewer_user_id=?",
            (resource_type, str(resource_id), str(user_id)),
        )
        self.connection.execute(
            "DELETE FROM resource_owners WHERE resource_type=? AND resource_id=? AND owner_user_id=?",
            (resource_type, str(resource_id), str(user_id)),
        )
        self._commit()

    def create_share(self, *, resource_type: str, resource_id: UUID, viewer: User, owner: User) -> ResourceShare:
        self.assert_access(resource_type=resource_type, resource_id=str(resource_id), user_id=owner.id, write=True)
        if viewer.id == owner.id:
            raise ValueError("Owner already has access")
        share = ResourceShare(
            id=uuid4(),
            resource_type=resource_type,
            resource_id=resource_id,
            viewer_user_id=viewer.id,
            created_by_user_id=owner.id,
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO resource_shares (id,resource_type,resource_id,viewer_user_id,role,created_by_user_id,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                str(share.id), share.resource_type, str(share.resource_id), str(share.viewer_user_id),
                share.role.value, str(share.created_by_user_id), _iso(share.created_at),
            ),
        )
        self._record_outbox("resource_share", share.id, "resource.share.created", str(owner.id), share.model_dump(mode="json"))
        self._commit()
        return share

    def list_shares(self, *, resource_type: str, resource_id: UUID, requester: User) -> list[ResourceShare]:
        self.assert_access(resource_type=resource_type, resource_id=str(resource_id), user_id=requester.id, write=True)
        rows = self.connection.execute(
            "SELECT id,resource_type,resource_id,viewer_user_id,role,created_by_user_id,created_at FROM resource_shares WHERE resource_type=? AND resource_id=? ORDER BY created_at",
            (resource_type, str(resource_id)),
        ).fetchall()
        return [
            ResourceShare(
                id=UUID(str(row[0])), resource_type=str(row[1]), resource_id=UUID(str(row[2])),
                viewer_user_id=UUID(str(row[3])), role=AccessRole(str(row[4])),
                created_by_user_id=UUID(str(row[5])), created_at=datetime.fromisoformat(str(row[6])),
            )
            for row in rows
        ]

    def revoke_share(self, *, resource_type: str, resource_id: UUID, viewer_user_id: UUID, owner: User) -> None:
        self.assert_access(resource_type=resource_type, resource_id=str(resource_id), user_id=owner.id, write=True)
        self.connection.execute(
            "DELETE FROM resource_shares WHERE resource_type=? AND resource_id=? AND viewer_user_id=?",
            (resource_type, str(resource_id), str(viewer_user_id)),
        )
        self._record_outbox("resource", resource_id, "resource.share.revoked", str(owner.id), {"viewer_user_id": str(viewer_user_id)})
        self._commit()

    def register_evidence(self, *, evidence: Evidence, owner: User) -> str:
        """Create a source/revision/evidence chain for a legacy-compatible Evidence object."""
        self.assign_owner(resource_type="asset", resource_id=evidence.asset_id, owner_user_id=owner.id)
        canonical_url = evidence.source_url or evidence.payload_ref or f"urn:evidence:{evidence.id}"
        source_id = self._source_id(owner.id, evidence.provenance.source_name, canonical_url, evidence.source_tier or "aggregator")
        document_key = evidence.payload_ref or canonical_url
        document_id = self._document_id(source_id, owner.id, document_key)
        normalized_hash = evidence.normalized_hash or self._hash(f"{evidence.title}\n{evidence.summary}")
        raw_hash = evidence.raw_hash or normalized_hash
        revision_id = self._revision_id(document_id, raw_hash, normalized_hash, evidence.published_at, evidence.data_version)
        row = self.connection.execute(
            "SELECT id FROM knowledge_evidence WHERE legacy_evidence_id=?", (str(evidence.id),)
        ).fetchone()
        if row is None:
            relational_id = str(uuid4())
            self.connection.execute(
                "INSERT INTO knowledge_evidence (id,legacy_evidence_id,asset_id,owner_user_id,source_revision_id,evidence_type,status,published_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    relational_id, str(evidence.id), str(evidence.asset_id), str(owner.id), revision_id,
                    evidence.evidence_type.value, evidence.status.value, _iso(evidence.published_at), _iso(evidence.created_at),
                ),
            )
            self.connection.execute(
                "INSERT INTO citations (id,evidence_id,source_revision_id,page_number,table_locator,cell_locator,excerpt,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid4()), relational_id, revision_id, None, None, None, evidence.summary[:1000], _iso(utc_now())),
            )
            self._record_outbox("evidence", evidence.id, "knowledge.evidence.registered", str(owner.id), {"knowledge_evidence_id": relational_id})
            self._commit()
            return relational_id
        return str(row[0])

    def submit_claim(self, claim: Claim, *, owner: User) -> Claim:
        self.assert_access(resource_type="asset", resource_id=str(claim.asset_id), user_id=owner.id, write=True)
        if claim.status is not ClaimStatus.PROPOSED:
            raise ValueError("New claims must start as proposed")
        knowledge_ids = [self._knowledge_evidence_id(evidence_id) for evidence_id in claim.evidence_ids]
        if any(item is None for item in knowledge_ids):
            raise ValueError("Claims require registered evidence")
        self.connection.execute(
            "INSERT INTO claims (id,asset_id,owner_user_id,statement,direction,status,confidence,valid_from,valid_until,contrary_claim_id,supersedes_claim_id,reviewed_by_user_id,reviewed_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(claim.id), str(claim.asset_id), str(claim.owner_user_id), claim.statement, claim.direction,
                claim.status.value, claim.confidence, _iso(claim.valid_from), _iso(claim.valid_until),
                None if claim.contrary_claim_id is None else str(claim.contrary_claim_id),
                None if claim.supersedes_claim_id is None else str(claim.supersedes_claim_id), None, None,
                _iso(claim.created_at), _iso(claim.updated_at),
            ),
        )
        for evidence_id, knowledge_id in zip(claim.evidence_ids, knowledge_ids):
            citation = self.connection.execute(
                "SELECT id FROM citations WHERE evidence_id=? ORDER BY created_at LIMIT 1", (knowledge_id,)
            ).fetchone()
            self.connection.execute(
                "INSERT INTO claim_evidence_links (claim_id,evidence_id,citation_id,relation) VALUES (?,?,?,?)",
                (str(claim.id), knowledge_id, None if citation is None else str(citation[0]), "supports"),
            )
        self._record_outbox("claim", claim.id, "claim.proposed", str(owner.id), claim.model_dump(mode="json"))
        self._commit()
        return claim

    def review_claim(self, *, claim_id: str, status: ClaimStatus, reviewer: User) -> Claim:
        if status not in {ClaimStatus.VERIFIED, ClaimStatus.REJECTED}:
            raise ValueError("Claims can only be reviewed as verified or rejected")
        row = self.connection.execute(
            "SELECT asset_id,owner_user_id,statement,direction,confidence,valid_from,valid_until,contrary_claim_id,supersedes_claim_id,created_at FROM claims WHERE id=?",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Claim not found")
        self.assert_access(resource_type="asset", resource_id=str(row[0]), user_id=reviewer.id, write=True)
        now = utc_now()
        self.connection.execute(
            "UPDATE claims SET status=?,reviewed_by_user_id=?,reviewed_at=?,updated_at=? WHERE id=?",
            (status.value, str(reviewer.id), _iso(now), _iso(now), claim_id),
        )
        evidence_rows = self.connection.execute(
            "SELECT ke.legacy_evidence_id FROM claim_evidence_links link JOIN knowledge_evidence ke ON ke.id=link.evidence_id WHERE link.claim_id=?",
            (claim_id,),
        ).fetchall()
        self._record_outbox("claim", UUID(claim_id), f"claim.{status.value}", str(reviewer.id), {"claim_id": claim_id})
        self._commit()
        return Claim(
            id=UUID(claim_id), asset_id=UUID(str(row[0])), owner_user_id=UUID(str(row[1])), statement=str(row[2]),
            direction=str(row[3]), status=status, confidence=float(row[4]),
            evidence_ids=[UUID(str(item[0])) for item in evidence_rows],
            valid_from=None if row[5] is None else datetime.fromisoformat(str(row[5])),
            valid_until=None if row[6] is None else datetime.fromisoformat(str(row[6])),
            contrary_claim_id=None if row[7] is None else UUID(str(row[7])),
            supersedes_claim_id=None if row[8] is None else UUID(str(row[8])),
            reviewed_by_user_id=reviewer.id, reviewed_at=now,
            created_at=datetime.fromisoformat(str(row[9])), updated_at=now,
        )

    def list_claims(self, *, asset_id: str, user: User) -> list[Claim]:
        self.assert_access(resource_type="asset", resource_id=asset_id, user_id=user.id)
        rows = self.connection.execute(
            "SELECT id,asset_id,owner_user_id,statement,direction,status,confidence,valid_from,valid_until,contrary_claim_id,supersedes_claim_id,reviewed_by_user_id,reviewed_at,created_at,updated_at FROM claims WHERE asset_id=? ORDER BY created_at DESC",
            (asset_id,),
        ).fetchall()
        claims: list[Claim] = []
        for row in rows:
            evidence_rows = self.connection.execute(
                "SELECT ke.legacy_evidence_id FROM claim_evidence_links link JOIN knowledge_evidence ke ON ke.id=link.evidence_id WHERE link.claim_id=?",
                (str(row[0]),),
            ).fetchall()
            claims.append(Claim(
                id=UUID(str(row[0])), asset_id=UUID(str(row[1])), owner_user_id=UUID(str(row[2])),
                statement=str(row[3]), direction=str(row[4]), status=ClaimStatus(str(row[5])), confidence=float(row[6]),
                evidence_ids=[UUID(str(item[0])) for item in evidence_rows],
                valid_from=None if row[7] is None else datetime.fromisoformat(str(row[7])),
                valid_until=None if row[8] is None else datetime.fromisoformat(str(row[8])),
                contrary_claim_id=None if row[9] is None else UUID(str(row[9])),
                supersedes_claim_id=None if row[10] is None else UUID(str(row[10])),
                reviewed_by_user_id=None if row[11] is None else UUID(str(row[11])),
                reviewed_at=None if row[12] is None else datetime.fromisoformat(str(row[12])),
                created_at=datetime.fromisoformat(str(row[13])), updated_at=datetime.fromisoformat(str(row[14])),
            ))
        return claims

    def record_research_run(self, *, run: AnalysisRun, owner: User, correlation_id: str) -> None:
        self.assign_owner(resource_type="analysis_run", resource_id=run.id, owner_user_id=owner.id)
        snapshot_hash = run.input_snapshot_hash or self._hash(str(run.id))
        existing = self.connection.execute(
            "SELECT snapshot_hash,state FROM research_runs_v2 WHERE run_id=?", (str(run.id),)
        ).fetchone()
        if existing is None:
            self.connection.execute(
                "INSERT INTO research_runs_v2 (run_id,owner_user_id,state,correlation_id,snapshot_hash,feature_contract_version,completed_at,archived_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    str(run.id), str(owner.id), "completed", correlation_id, snapshot_hash,
                    run.feature_contract_version, _iso(utc_now()), None, _iso(run.created_at),
                ),
            )
        elif str(existing[0]) != snapshot_hash or str(existing[1]) not in {"completed", "archived"}:
            raise ValueError("Completed research run is immutable")
        for evidence_id in run.evidence_ids:
            knowledge_id = self._knowledge_evidence_id(evidence_id)
            if knowledge_id is not None:
                self.connection.execute(
                    "INSERT OR IGNORE INTO research_run_evidence (run_id,evidence_id) VALUES (?,?)",
                    (str(run.id), knowledge_id),
                )
        self._record_outbox("research_run", run.id, "research_run.completed", correlation_id, {"run_id": str(run.id)})
        self._commit()

    def archive_research_run(self, *, run_id: str, owner: User) -> None:
        self.assert_access(resource_type="analysis_run", resource_id=run_id, user_id=owner.id, write=True)
        row = self.connection.execute("SELECT state FROM research_runs_v2 WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Research run not found")
        if str(row[0]) == "archived":
            return
        self.connection.execute(
            "UPDATE research_runs_v2 SET state='archived', archived_at=? WHERE run_id=?",
            (_iso(utc_now()), run_id),
        )
        self._record_outbox("research_run", UUID(run_id), "research_run.archived", run_id, {"run_id": run_id})
        self._commit()

    def record_gate_evaluation(self, *, run: AnalysisRun, owner: User, verdict: JudgeVerdict, score: float, reasons: list[str], correlation_id: str) -> GateEvaluation:
        self.record_research_run(run=run, owner=owner, correlation_id=correlation_id)
        policy_id = self._ensure_gate_policy()
        evaluation = GateEvaluation(
            id=uuid4(), research_run_id=run.id, policy_version="quality-gate-v1", correlation_id=correlation_id,
            verdict=verdict, score=score,
            findings=[GateFinding(rule_key=f"gate-{index + 1}", severity=verdict, passed=False, reason=reason) for index, reason in enumerate(reasons)],
        )
        self.connection.execute(
            "INSERT INTO gate_evaluations (id,research_run_id,policy_id,correlation_id,verdict,score,created_at) VALUES (?,?,?,?,?,?,?)",
            (str(evaluation.id), str(run.id), policy_id, correlation_id, verdict.value, score, _iso(evaluation.created_at)),
        )
        for finding in evaluation.findings:
            self.connection.execute(
                "INSERT INTO gate_findings (id,gate_evaluation_id,rule_key,severity,passed,reason) VALUES (?,?,?,?,?,?)",
                (str(uuid4()), str(evaluation.id), finding.rule_key, finding.severity.value, int(finding.passed), finding.reason),
            )
        self._record_outbox("gate_evaluation", evaluation.id, "quality_gate.evaluated", correlation_id, evaluation.model_dump(mode="json"))
        self._commit()
        return evaluation

    def record_model_inference(self, *, run: AnalysisRun, prediction: ModelPrediction, owner: User, correlation_id: str) -> None:
        self.record_research_run(run=run, owner=owner, correlation_id=correlation_id)
        feature_contract_id = self._ensure_feature_contract(prediction.manifest_version or run.feature_contract_version)
        model_id = self._ensure_model_version(prediction, feature_contract_id)
        model_run_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO model_runs (id,research_run_id,model_version_id,correlation_id,input_hash,state,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                model_run_id, str(run.id), model_id, correlation_id,
                run.feature_vector_hash or run.input_snapshot_hash or self._hash(str(run.id)),
                "completed", _iso(utc_now()),
            ),
        )
        self.connection.execute(
            "INSERT INTO inference_outputs (id,model_run_id,risk_probability,feature_coverage,abstained,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                str(uuid4()), model_run_id, prediction.risk_probability, prediction.feature_coverage,
                int(prediction.feature_coverage < 0.75), prediction.model_dump_json(), _iso(utc_now()),
            ),
        )
        self._record_outbox("model_run", UUID(model_run_id), "model.inference.completed", correlation_id, {"prediction_id": str(prediction.id)})
        self._commit()

    def record_portfolio_snapshot(self, *, snapshot: PortfolioRiskSnapshot, owner: User, correlation_id: str, research_run_id: UUID | None = None) -> None:
        snapshot_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO portfolio_snapshots_v2 (id,owner_user_id,research_run_id,correlation_id,as_of,created_at) VALUES (?,?,?,?,?,?)",
            (snapshot_id, str(owner.id), None if research_run_id is None else str(research_run_id), correlation_id, _iso(snapshot.as_of), _iso(snapshot.created_at)),
        )
        for dimension, values in (("market", snapshot.market_exposure), ("industry", snapshot.industry_exposure)):
            for key, weight in values.items():
                self.connection.execute(
                    "INSERT INTO portfolio_exposures (id,portfolio_snapshot_id,dimension,dimension_key,weight) VALUES (?,?,?,?,?)",
                    (str(uuid4()), snapshot_id, dimension, key, weight),
                )
        for position_id, contribution in snapshot.position_risk_contributions.items():
            self.connection.execute(
                "INSERT INTO risk_contributions (id,portfolio_snapshot_id,position_id,contribution) VALUES (?,?,?,?)",
                (str(uuid4()), snapshot_id, position_id if self._position_exists(position_id) else None, contribution),
            )
        for scenario, impact in snapshot.stress_scenarios.items():
            self.connection.execute(
                "INSERT INTO stress_results (id,portfolio_snapshot_id,scenario_key,impact) VALUES (?,?,?,?)",
                (str(uuid4()), snapshot_id, scenario, impact),
            )
        self._record_outbox("portfolio_snapshot", UUID(snapshot_id), "portfolio.snapshot.created", correlation_id, {"legacy_snapshot_id": str(snapshot.id)})
        self._commit()

    def _source_id(self, owner_id: UUID, source_name: str, canonical_url: str, tier: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM knowledge_sources WHERE owner_user_id=? AND canonical_url=?", (str(owner_id), canonical_url)
        ).fetchone()
        if row is not None:
            return str(row[0])
        source_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO knowledge_sources (id,owner_user_id,source_name,canonical_url,source_tier,created_at) VALUES (?,?,?,?,?,?)",
            (source_id, str(owner_id), source_name, canonical_url, tier, _iso(utc_now())),
        )
        return source_id

    def _document_id(self, source_id: str, owner_id: UUID, document_key: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM source_documents WHERE source_id=? AND document_key=?", (source_id, document_key)
        ).fetchone()
        if row is not None:
            return str(row[0])
        document_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO source_documents (id,source_id,owner_user_id,document_key,content_type,created_at) VALUES (?,?,?,?,?,?)",
            (document_id, source_id, str(owner_id), document_key, "application/json", _iso(utc_now())),
        )
        return document_id

    def _revision_id(self, document_id: str, raw_hash: str, normalized_hash: str, published_at: datetime | None, data_version: str | None) -> str:
        row = self.connection.execute(
            "SELECT id FROM source_revisions WHERE document_id=? AND normalized_hash=?", (document_id, normalized_hash)
        ).fetchone()
        if row is not None:
            return str(row[0])
        revision_id = str(uuid4())
        revision_number = int(self.connection.execute(
            "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM source_revisions WHERE document_id=?", (document_id,)
        ).fetchone()[0])
        self.connection.execute(
            "INSERT INTO source_revisions (id,document_id,revision_number,published_at,raw_hash,normalized_hash,object_key,metadata_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (revision_id, document_id, revision_number, _iso(published_at), raw_hash, normalized_hash, None, json.dumps({"data_version": data_version}), _iso(utc_now())),
        )
        return revision_id

    def _knowledge_evidence_id(self, legacy_evidence_id: UUID) -> str | None:
        row = self.connection.execute("SELECT id FROM knowledge_evidence WHERE legacy_evidence_id=?", (str(legacy_evidence_id),)).fetchone()
        return None if row is None else str(row[0])

    def _ensure_gate_policy(self) -> str:
        row = self.connection.execute("SELECT id FROM quality_gate_policies WHERE version='quality-gate-v1'").fetchone()
        if row is not None:
            return str(row[0])
        policy_id = str(uuid4())
        rules = {"version": "quality-gate-v1", "input": "immutable research run snapshot"}
        self.connection.execute(
            "INSERT INTO quality_gate_policies (id,version,rules_json,created_at) VALUES (?,?,?,?)",
            (policy_id, "quality-gate-v1", json.dumps(rules), _iso(utc_now())),
        )
        return policy_id

    def _ensure_feature_contract(self, version: str | None) -> str:
        resolved_version = version or "legacy-unknown"
        row = self.connection.execute("SELECT id FROM feature_contracts WHERE version=?", (resolved_version,)).fetchone()
        if row is not None:
            return str(row[0])
        contract_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO feature_contracts (id,version,feature_order_json,scaler_object_key,created_at) VALUES (?,?,?,?,?)",
            (contract_id, resolved_version, "[]", None, _iso(utc_now())),
        )
        return contract_id

    def _ensure_model_version(self, prediction: ModelPrediction, feature_contract_id: str) -> str:
        model_key = f"{prediction.model_name}@{prediction.model_version}"
        row = self.connection.execute("SELECT id FROM model_versions WHERE model_id=?", (model_key,)).fetchone()
        if row is not None:
            return str(row[0])
        model_version_id = str(uuid4())
        status = "approved" if prediction.deployment_approved else "candidate"
        self.connection.execute(
            "INSERT INTO model_versions (id,model_id,status,feature_contract_id,artifact_key,metadata_json,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                model_version_id, model_key, status, feature_contract_id,
                f"manifest://{prediction.manifest_version or 'legacy'}",
                json.dumps({"target_name": prediction.target_name, "model_status": prediction.model_status}), _iso(utc_now()),
            ),
        )
        return model_version_id

    def _position_exists(self, position_id: str) -> bool:
        return self.connection.execute("SELECT 1 FROM positions WHERE id=?", (position_id,)).fetchone() is not None

    def _record_outbox(self, aggregate_type: str, aggregate_id: UUID, event_type: str, correlation_id: str, payload: dict) -> None:
        self.connection.execute(
            "INSERT INTO outbox_events (id,aggregate_type,aggregate_id,event_type,correlation_id,payload_json,state,attempts,occurred_at,processed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), aggregate_type, str(aggregate_id), event_type, correlation_id, json.dumps(payload, default=str), "pending", 0, _iso(utc_now()), None),
        )

    def _hash(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _commit(self) -> None:
        self.connection.commit()
