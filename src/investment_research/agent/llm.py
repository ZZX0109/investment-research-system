from __future__ import annotations

import json
import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from investment_research.agent.models import ProviderProfile


T = TypeVar("T", bound=BaseModel)


class LLMProviderError(RuntimeError):
    pass


class LLMRequest(BaseModel, Generic[T]):
    node_name: str
    system_prompt: str
    user_payload: dict[str, object]
    response_schema: dict[str, object]
    response_model_name: str
    prompt_version: str = "agent-v1"
    schema_version: str = "1.0"
    max_output_tokens: int
    evidence_ids: list[str] = Field(default_factory=list)


class LLMResponse(BaseModel, Generic[T]):
    output: T
    provider_protocol: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw_response: dict[str, object] = Field(default_factory=dict)


class LLMProvider(Protocol):
    def generate_structured(self, request: LLMRequest[T], response_model: type[T]) -> LLMResponse[T]: ...


def _token_estimate(value: object) -> int:
    return max(1, len(json.dumps(value, ensure_ascii=False, default=str)) // 3)


@dataclass
class HTTPStructuredProvider:
    profile: ProviderProfile
    api_key: str | None = None

    def generate_structured(self, request: LLMRequest[T], response_model: type[T]) -> LLMResponse[T]:
        if not self.profile.endpoint:
            raise LLMProviderError("Provider endpoint is required")
        self._validate_runtime_endpoint()
        started = time.perf_counter()
        payload, headers = self._payload(request)
        http_request = Request(
            self.profile.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urlopen(http_request, timeout=self.profile.timeout_seconds) as response:  # noqa: S310 - operator-configured endpoint
                body = json.loads(response.read().decode("utf-8"))
            content = self._content(body)
            parsed = json.loads(content) if isinstance(content, str) else content
            output = response_model.model_validate(parsed)
        except Exception as exc:
            raise LLMProviderError(f"Structured LLM call failed: {type(exc).__name__}") from exc
        return LLMResponse(
            output=output,
            provider_protocol=self.profile.protocol,
            model=self.profile.model,
            input_tokens=int(body.get("usage", {}).get("prompt_tokens", _token_estimate(payload))),
            output_tokens=int(body.get("usage", {}).get("completion_tokens", _token_estimate(parsed))),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response={"id": body.get("id"), "model": body.get("model")},
        )

    def _payload(self, request: LLMRequest[T]) -> tuple[dict[str, object], dict[str, str]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.profile.protocol == "anthropic_messages":
            if self.api_key:
                headers.pop("Authorization", None)
                headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = "2023-06-01"
            return {
                "model": self.profile.model,
                "system": request.system_prompt,
                "messages": [{"role": "user", "content": json.dumps({"payload": request.user_payload, "response_schema": request.response_schema}, ensure_ascii=False)}],
                "max_tokens": request.max_output_tokens,
            }, headers
        if self.profile.protocol == "ollama":
            return {
                "model": self.profile.model,
                "stream": False,
                "format": request.response_schema,
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": json.dumps(request.user_payload, ensure_ascii=False)},
                ],
            }, headers
        return {
            "model": self.profile.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": json.dumps(request.user_payload, ensure_ascii=False)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": request.response_model_name, "strict": True, "schema": request.response_schema},
            },
            "max_tokens": request.max_output_tokens,
        }, headers

    def _content(self, body: dict[str, object]) -> object:
        if self.profile.protocol == "anthropic_messages":
            blocks = body.get("content") or []
            return blocks[0]["text"]  # type: ignore[index]
        if self.profile.protocol == "ollama":
            return body.get("message", {}).get("content")  # type: ignore[union-attr]
        return body.get("choices", [])[0]["message"]["content"]  # type: ignore[index]

    def _validate_runtime_endpoint(self) -> None:
        endpoint = self.profile.endpoint or ""
        parsed = urlparse(endpoint)
        host = parsed.hostname
        if not host or self.profile.protocol == "ollama" and host in {"localhost", "127.0.0.1", "::1"}:
            return
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise LLMProviderError("Provider hostname could not be resolved") from exc
        for value in addresses:
            address = ipaddress.ip_address(value)
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                raise LLMProviderError("Provider hostname resolves to a non-public address")


class MockProvider:
    def __init__(self, profile: ProviderProfile) -> None:
        self.profile = profile

    def generate_structured(self, request: LLMRequest[T], response_model: type[T]) -> LLMResponse[T]:
        started = time.perf_counter()
        evidence_ids = request.user_payload.get("evidence_ids", [])
        defaults: dict[str, dict[str, object]] = {
            "TaskClassification": {
                "task_type": "single_asset_risk_research", "research_scope": "asset",
                "horizon": "20d", "user_preference": request.user_payload.get("user_preference", "conservative"),
                "evidence_ids": evidence_ids,
            },
            "AgentPlan": {
                "template_id": "single-asset-risk-v1",
                "tool_ids": ["collect_pit_evidence", "build_29_features", "approved_model_inference", "historical_analogy", "quality_gate"],
                "observation_focus": ["drawdown risk", "event conflict", "data freshness"],
                "evidence_ids": evidence_ids,
            },
            "CounterEvidenceQuery": {
                "query_terms": ["risk", "regulatory", "guidance cut"],
                "challenged_claim": "The base risk conclusion may omit contrary evidence.",
                "evidence_ids": evidence_ids,
            },
            "CitationAudit": {
                "supported": bool(evidence_ids), "unsupported_claims": [] if evidence_ids else ["No cited evidence"],
                "missing_counter_view": False, "evidence_ids": evidence_ids,
            },
            "ReportNarrative": {
                "summary": "The result is evidence-bound and limited to a 20-day drawdown-risk observation.",
                "supporting_view": "Approved model output and point-in-time evidence support the stated risk range.",
                "contrary_view": "Conflicting or stale evidence can weaken the conclusion.",
                "observation_conditions": ["Refresh after material filings", "Abstain when evidence or features are insufficient"],
                "evidence_ids": evidence_ids, "contains_trade_instruction": False,
            },
        }
        output = response_model.model_validate(defaults.get(response_model.__name__, {}))
        return LLMResponse(
            output=output,
            provider_protocol="mock",
            model=self.profile.model,
            input_tokens=_token_estimate(request.user_payload),
            output_tokens=_token_estimate(output.model_dump(mode="json")),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def build_llm_provider(profile: ProviderProfile, api_key: str | None = None) -> LLMProvider:
    if profile.protocol == "mock":
        return MockProvider(profile)
    return HTTPStructuredProvider(profile, api_key=api_key)
