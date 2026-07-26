from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from investment_research.agent.models import AgentBudget, AgentEvent, AgentRun, AgentRunState, AgentToolCall, ProviderProfile


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def stable_hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class AgentRuntimeRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def add_run(self, run: AgentRun) -> AgentRun:
        self.connection.execute(
            """
            INSERT INTO agent_runs (
                id,owner_user_id,asset_id,research_run_id,report_id,provider_profile_id,
                task_type,task_text,user_preference,as_of,state,current_node,correlation_id,
                verdict,abstain_reason,llm_calls_used,tool_calls_used,input_tokens_used,
                output_tokens_used,repair_count,created_at,updated_at,completed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(run.id), str(run.owner_user_id), str(run.asset_id),
                None if run.research_run_id is None else str(run.research_run_id),
                None if run.report_id is None else str(run.report_id),
                None if run.provider_profile_id is None else str(run.provider_profile_id),
                run.task_type, run.task_text, run.user_preference, _iso(run.as_of), run.state.value,
                run.current_node, run.correlation_id, run.verdict, run.abstain_reason,
                run.budget.llm_calls_used, run.budget.tool_calls_used,
                run.budget.input_tokens_used, run.budget.output_tokens_used,
                run.budget.repair_count, _iso(run.created_at), _iso(run.updated_at),
                _iso(run.completed_at),
            ),
        )
        self.connection.commit()
        return run

    def update_run(self, run: AgentRun) -> AgentRun:
        self.connection.execute(
            """
            UPDATE agent_runs SET research_run_id=?,report_id=?,provider_profile_id=?,state=?,
            current_node=?,verdict=?,abstain_reason=?,llm_calls_used=?,tool_calls_used=?,
            input_tokens_used=?,output_tokens_used=?,repair_count=?,updated_at=?,completed_at=?
            WHERE id=? AND owner_user_id=?
            """,
            (
                None if run.research_run_id is None else str(run.research_run_id),
                None if run.report_id is None else str(run.report_id),
                None if run.provider_profile_id is None else str(run.provider_profile_id),
                run.state.value, run.current_node, run.verdict, run.abstain_reason,
                run.budget.llm_calls_used, run.budget.tool_calls_used,
                run.budget.input_tokens_used, run.budget.output_tokens_used,
                run.budget.repair_count, _iso(run.updated_at), _iso(run.completed_at),
                str(run.id), str(run.owner_user_id),
            ),
        )
        self.connection.commit()
        return run

    def get_run(self, run_id: str, owner_user_id: UUID | None = None) -> AgentRun | None:
        sql = "SELECT * FROM agent_runs WHERE id=?"
        params: tuple[object, ...] = (run_id,)
        if owner_user_id is not None:
            sql += " AND owner_user_id=?"
            params += (str(owner_user_id),)
        row = self.connection.execute(sql, params).fetchone()
        return None if row is None else self._run_from_row(row)

    def add_event(self, run_id: UUID, event_type: str, *, node_name: str | None = None, payload: dict[str, object] | None = None) -> AgentEvent:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM agent_events WHERE agent_run_id=?",
            (str(run_id),),
        ).fetchone()
        event = AgentEvent(
            agent_run_id=run_id,
            sequence=int(row[0]),
            event_type=event_type,
            node_name=node_name,
            payload=payload or {},
        )
        self.connection.execute(
            "INSERT INTO agent_events (id,agent_run_id,sequence,event_type,node_name,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
            (str(event.id), str(run_id), event.sequence, event.event_type, node_name, _json(event.payload), _iso(event.created_at)),
        )
        self.connection.commit()
        return event

    def list_events(self, run_id: str) -> list[AgentEvent]:
        rows = self.connection.execute(
            "SELECT id,agent_run_id,sequence,event_type,node_name,payload_json,created_at FROM agent_events WHERE agent_run_id=? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        return [
            AgentEvent(
                id=UUID(str(row[0])), agent_run_id=UUID(str(row[1])), sequence=int(row[2]),
                event_type=str(row[3]), node_name=None if row[4] is None else str(row[4]),
                payload=json.loads(str(row[5])), created_at=datetime.fromisoformat(str(row[6])),
            )
            for row in rows
        ]

    def start_node(self, run: AgentRun, node_name: str, input_value: object) -> str:
        attempt_row = self.connection.execute(
            "SELECT COALESCE(MAX(attempt),0)+1 FROM agent_node_executions WHERE agent_run_id=? AND node_name=?",
            (str(run.id), node_name),
        ).fetchone()
        execution_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO agent_node_executions (id,agent_run_id,node_name,attempt,state,input_hash,output_json,error,started_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (execution_id, str(run.id), node_name, int(attempt_row[0]), "running", stable_hash(input_value), "{}", None, _iso(datetime.now(timezone.utc)), None),
        )
        self.connection.commit()
        self.add_event(run.id, "node.started", node_name=node_name)
        return execution_id

    def finish_node(self, execution_id: str, run_id: UUID, node_name: str, output: object, *, error: str | None = None) -> None:
        state = "failed" if error else "completed"
        safe_error = None if error is None else error[:500]
        self.connection.execute(
            "UPDATE agent_node_executions SET state=?,output_json=?,error=?,completed_at=? WHERE id=?",
            (state, _json(output), safe_error, _iso(datetime.now(timezone.utc)), execution_id),
        )
        self.connection.commit()
        self.add_event(run_id, f"node.{state}", node_name=node_name, payload={"error": safe_error} if safe_error else {})

    def add_plan(self, run_id: UUID, plan: object) -> None:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(revision_number),0)+1 FROM agent_plan_revisions WHERE agent_run_id=?",
            (str(run_id),),
        ).fetchone()
        payload = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
        self.connection.execute(
            "INSERT INTO agent_plan_revisions (id,agent_run_id,revision_number,plan_json,plan_hash,created_at) VALUES (?,?,?,?,?,?)",
            (str(uuid4()), str(run_id), int(row[0]), _json(payload), stable_hash(payload), _iso(datetime.now(timezone.utc))),
        )
        self.connection.commit()

    def add_tool_call(self, run_id: UUID, node_name: str, tool_id: str, input_value: object, output: object | None, *, error: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        self.connection.execute(
            "INSERT INTO agent_tool_calls (id,agent_run_id,node_name,tool_id,input_hash,output_hash,state,error,started_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), str(run_id), node_name, tool_id, stable_hash(input_value), None if output is None else stable_hash(output), "failed" if error else "completed", None if error is None else error[:500], _iso(now), _iso(now)),
        )
        self.connection.commit()

    def list_tool_calls(self, run_id: str) -> list[AgentToolCall]:
        rows = self.connection.execute(
            """
            SELECT id,agent_run_id,node_name,tool_id,input_hash,output_hash,state,error,started_at,completed_at
            FROM agent_tool_calls WHERE agent_run_id=? ORDER BY started_at,id
            """,
            (run_id,),
        ).fetchall()
        return [
            AgentToolCall(
                id=UUID(str(row[0])),
                agent_run_id=UUID(str(row[1])),
                node_name=str(row[2]),
                tool_id=str(row[3]),
                input_hash=str(row[4]),
                output_hash=None if row[5] is None else str(row[5]),
                state=str(row[6]),
                error=None if row[7] is None else str(row[7]),
                started_at=datetime.fromisoformat(str(row[8])),
                completed_at=None if row[9] is None else datetime.fromisoformat(str(row[9])),
            )
            for row in rows
        ]

    def get_cache(self, cache_key: str) -> dict[str, object] | None:
        row = self.connection.execute(
            "SELECT response_json FROM llm_cache_entries WHERE cache_key=? AND expires_at>?",
            (cache_key, _iso(datetime.now(timezone.utc))),
        ).fetchone()
        return None if row is None else json.loads(str(row[0]))

    def put_cache(self, cache_key: str, response: dict[str, object]) -> None:
        now = datetime.now(timezone.utc)
        self.connection.execute(
            "INSERT OR REPLACE INTO llm_cache_entries (cache_key,response_json,created_at,expires_at) VALUES (?,?,?,?)",
            (cache_key, _json(response), _iso(now), _iso(now + timedelta(hours=24))),
        )
        self.connection.commit()

    def add_llm_call(self, *, run_id: UUID, node_name: str, protocol: str, model: str, prompt_version: str, schema_version: str, request_hash: str, evidence_hash: str, input_tokens: int, output_tokens: int, latency_ms: int, cache_hit: bool, state: str, error: str | None = None) -> None:
        self.connection.execute(
            "INSERT INTO llm_calls (id,agent_run_id,node_name,provider_protocol,model,prompt_version,schema_version,request_hash,evidence_hash,input_tokens,output_tokens,latency_ms,cache_hit,state,error,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), str(run_id), node_name, protocol, model, prompt_version, schema_version, request_hash, evidence_hash, input_tokens, output_tokens, latency_ms, cache_hit, state, None if error is None else error[:500], _iso(datetime.now(timezone.utc))),
        )
        self.connection.commit()

    def add_profile(self, profile: ProviderProfile) -> ProviderProfile:
        self.connection.execute(
            "INSERT INTO llm_provider_profiles (id,owner_user_id,name,protocol,endpoint,model,credential_ref,timeout_seconds,context_limit,fallback_profile_id,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(profile.id), str(profile.owner_user_id), profile.name, profile.protocol, profile.endpoint, profile.model, profile.credential_ref, profile.timeout_seconds, profile.context_limit, None if profile.fallback_profile_id is None else str(profile.fallback_profile_id), profile.enabled, _iso(profile.created_at), _iso(profile.updated_at)),
        )
        self.connection.commit()
        return profile

    def get_profile(self, profile_id: str, owner_user_id: UUID) -> ProviderProfile | None:
        row = self.connection.execute(
            "SELECT * FROM llm_provider_profiles WHERE id=? AND owner_user_id=?",
            (profile_id, str(owner_user_id)),
        ).fetchone()
        return None if row is None else self._profile_from_row(row)

    def list_profiles(self, owner_user_id: UUID) -> list[ProviderProfile]:
        rows = self.connection.execute(
            "SELECT * FROM llm_provider_profiles WHERE owner_user_id=? ORDER BY name",
            (str(owner_user_id),),
        ).fetchall()
        return [self._profile_from_row(row) for row in rows]

    def update_profile(self, profile: ProviderProfile) -> ProviderProfile:
        self.connection.execute(
            """
            UPDATE llm_provider_profiles SET name=?,protocol=?,endpoint=?,model=?,credential_ref=?,
            timeout_seconds=?,context_limit=?,fallback_profile_id=?,enabled=?,updated_at=?
            WHERE id=? AND owner_user_id=?
            """,
            (
                profile.name, profile.protocol, profile.endpoint, profile.model, profile.credential_ref,
                profile.timeout_seconds, profile.context_limit,
                None if profile.fallback_profile_id is None else str(profile.fallback_profile_id),
                profile.enabled, _iso(profile.updated_at), str(profile.id), str(profile.owner_user_id),
            ),
        )
        self.connection.commit()
        return profile

    def delete_profile(self, profile_id: str, owner_user_id: UUID) -> bool:
        cursor = self.connection.execute(
            "DELETE FROM llm_provider_profiles WHERE id=? AND owner_user_id=?",
            (profile_id, str(owner_user_id)),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def add_paper_prediction(
        self,
        *,
        owner_user_id: UUID,
        asset_id: UUID,
        research_run_id: UUID,
        model_role: str,
        model_id: str,
        as_of: datetime,
        risk_probability: float | None,
        feature_coverage: float,
        abstained: bool,
        feature_values: list[float] | None = None,
        provider_missing_rate: float = 0.0,
    ) -> str:
        prediction_id = str(uuid4())
        if risk_probability is None:
            bucket = "abstained"
        elif risk_probability >= 0.8:
            bucket = "top_20pct"
        elif risk_probability >= 0.65:
            bucket = "high"
        elif risk_probability >= 0.35:
            bucket = "medium"
        else:
            bucket = "low"
        self.connection.execute(
            """
            INSERT INTO paper_predictions_v2 (
                id,owner_user_id,inference_output_id,asset_id,research_run_id,model_role,
                model_id,as_of,risk_probability,risk_bucket,feature_coverage,abstained,
                evaluation_due_at,created_at,feature_values_json,provider_missing_rate
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                prediction_id, str(owner_user_id), None, str(asset_id), str(research_run_id),
                model_role, model_id, _iso(as_of), risk_probability, bucket, feature_coverage,
                abstained, _iso(as_of + timedelta(days=28)), _iso(datetime.now(timezone.utc)),
                None if feature_values is None else _json(feature_values), provider_missing_rate,
            ),
        )
        self.connection.commit()
        return prediction_id

    def paper_summary(self, owner_user_id: UUID) -> dict[str, object]:
        rows = self.connection.execute(
            """
            SELECT p.model_role,p.risk_bucket,p.abstained,p.risk_probability,o.realized_max_drawdown,o.alert_lead_days
            FROM paper_predictions_v2 p LEFT JOIN paper_outcomes o ON o.paper_prediction_id=p.id
            WHERE p.owner_user_id=?
            """,
            (str(owner_user_id),),
        ).fetchall()
        by_model: dict[str, dict[str, object]] = {}
        for row in rows:
            role = str(row[0])
            record = by_model.setdefault(role, {"prediction_count": 0, "evaluated_count": 0, "abstained_count": 0, "top_bucket_drawdowns": [], "all_drawdowns": []})
            record["prediction_count"] = int(record["prediction_count"]) + 1
            if bool(row[2]):
                record["abstained_count"] = int(record["abstained_count"]) + 1
            if row[4] is not None:
                record["evaluated_count"] = int(record["evaluated_count"]) + 1
                record["all_drawdowns"].append(float(row[4]))  # type: ignore[union-attr]
                if str(row[1]) == "top_20pct":
                    record["top_bucket_drawdowns"].append(float(row[4]))  # type: ignore[union-attr]
        for record in by_model.values():
            all_values = record.pop("all_drawdowns")
            top_values = record.pop("top_bucket_drawdowns")
            mean_all = sum(all_values) / len(all_values) if all_values else None
            mean_top = sum(top_values) / len(top_values) if top_values else None
            record["mean_realized_drawdown"] = mean_all
            record["top_bucket_mean_drawdown"] = mean_top
            record["drawdown_lift"] = None if mean_all is None or mean_top is None else mean_all - mean_top
        return {"prospective": by_model, "prediction_count": len(rows)}

    def due_paper_predictions(self, as_of: datetime) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT p.id,p.owner_user_id,p.asset_id,p.research_run_id,p.model_role,p.model_id,
                   p.as_of,p.risk_probability,p.feature_coverage,p.abstained,p.evaluation_due_at
            FROM paper_predictions_v2 p LEFT JOIN paper_outcomes o ON o.paper_prediction_id=p.id
            WHERE o.id IS NULL AND p.evaluation_due_at<=? ORDER BY p.evaluation_due_at LIMIT 500
            """,
            (_iso(as_of),),
        ).fetchall()
        keys = ("id", "owner_user_id", "asset_id", "research_run_id", "model_role", "model_id", "as_of", "risk_probability", "feature_coverage", "abstained", "evaluation_due_at")
        return [dict(zip(keys, row)) for row in rows]

    def add_paper_outcome(self, *, prediction_id: str, realized_max_drawdown: float, alert_lead_days: int | None, evaluated_at: datetime) -> None:
        existing = self.connection.execute(
            "SELECT 1 FROM paper_outcomes WHERE paper_prediction_id=?", (prediction_id,)
        ).fetchone()
        if existing is not None:
            return
        self.connection.execute(
            "INSERT INTO paper_outcomes (id,paper_prediction_id,realized_max_drawdown,alert_lead_days,evaluated_at) VALUES (?,?,?,?,?)",
            (str(uuid4()), prediction_id, realized_max_drawdown, alert_lead_days, _iso(evaluated_at)),
        )
        self.connection.commit()

    def drift_exists(self, model_id: str, period_start: datetime, period_end: datetime) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM drift_evaluations WHERE model_id=? AND period_start=? AND period_end=?",
            (model_id, _iso(period_start), _iso(period_end)),
        ).fetchone() is not None

    def add_drift_evaluation(self, *, period_start: datetime, period_end: datetime, model_id: str, psi: float | None, ece: float | None, brier: float | None, drawdown_lift: float | None, feature_coverage: float, abstention_rate: float, provider_missing_rate: float, verdict: str) -> None:
        self.connection.execute(
            "INSERT INTO drift_evaluations (id,period_start,period_end,model_id,psi,ece,brier,drawdown_lift,feature_coverage,abstention_rate,provider_missing_rate,verdict,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), _iso(period_start), _iso(period_end), model_id, psi, ece, brier, drawdown_lift, feature_coverage, abstention_rate, provider_missing_rate, verdict, _iso(datetime.now(timezone.utc))),
        )
        self.connection.commit()

    def latest_drift_verdict(self, model_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT verdict FROM drift_evaluations WHERE model_id=? ORDER BY period_end DESC LIMIT 1",
            (model_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    def evaluated_paper_rows(self, period_start: datetime, period_end: datetime) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT p.model_id,p.risk_probability,p.feature_coverage,p.abstained,o.realized_max_drawdown,
                   p.feature_values_json,p.provider_missing_rate
            FROM paper_predictions_v2 p JOIN paper_outcomes o ON o.paper_prediction_id=p.id
            WHERE o.evaluated_at>=? AND o.evaluated_at<?
            """,
            (_iso(period_start), _iso(period_end)),
        ).fetchall()
        keys = ("model_id", "risk_probability", "feature_coverage", "abstained", "realized_max_drawdown", "feature_values_json", "provider_missing_rate")
        return [dict(zip(keys, row)) for row in rows]

    def _run_from_row(self, row) -> AgentRun:
        return AgentRun(
            id=UUID(str(row[0])), owner_user_id=UUID(str(row[1])), asset_id=UUID(str(row[2])),
            research_run_id=None if row[3] is None else UUID(str(row[3])),
            report_id=None if row[4] is None else UUID(str(row[4])),
            provider_profile_id=None if row[5] is None else UUID(str(row[5])),
            task_type=str(row[6]), task_text=str(row[7]), user_preference=str(row[8]),
            as_of=datetime.fromisoformat(str(row[9])), state=AgentRunState(str(row[10])),
            current_node=None if row[11] is None else str(row[11]), correlation_id=str(row[12]),
            verdict=None if row[13] is None else str(row[13]), abstain_reason=None if row[14] is None else str(row[14]),
            budget=AgentBudget(llm_calls_used=int(row[15]), tool_calls_used=int(row[16]), input_tokens_used=int(row[17]), output_tokens_used=int(row[18]), repair_count=int(row[19])),
            created_at=datetime.fromisoformat(str(row[20])), updated_at=datetime.fromisoformat(str(row[21])),
            completed_at=None if row[22] is None else datetime.fromisoformat(str(row[22])),
        )

    def _profile_from_row(self, row) -> ProviderProfile:
        return ProviderProfile(
            id=UUID(str(row[0])), owner_user_id=UUID(str(row[1])), name=str(row[2]), protocol=str(row[3]),
            endpoint=None if row[4] is None else str(row[4]), model=str(row[5]), credential_ref=None if row[6] is None else str(row[6]),
            timeout_seconds=float(row[7]), context_limit=int(row[8]), fallback_profile_id=None if row[9] is None else UUID(str(row[9])),
            enabled=bool(row[10]), created_at=datetime.fromisoformat(str(row[11])), updated_at=datetime.fromisoformat(str(row[12])),
        )
