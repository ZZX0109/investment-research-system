from __future__ import annotations

import json
import ipaddress
import os
import socket
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
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


class LLMToolDefinition(BaseModel):
    """A provider-neutral, allow-listed function exposed to the research agent."""

    name: str
    description: str
    parameters: dict[str, object]


class LLMToolInvocation(BaseModel):
    """One function request returned by a compatible chat-completions provider."""

    id: str
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class LLMToolRequest(BaseModel):
    node_name: str
    system_prompt: str
    messages: list[dict[str, object]]
    tools: list[LLMToolDefinition]
    max_output_tokens: int
    prompt_version: str = "research-function-call-v1"


class LLMToolResponse(BaseModel):
    tool_calls: list[LLMToolInvocation] = Field(default_factory=list)
    content: str | None = None
    provider_protocol: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw_response: dict[str, object] = Field(default_factory=dict)


class LLMProvider(Protocol):
    def generate_structured(self, request: LLMRequest[T], response_model: type[T]) -> LLMResponse[T]: ...

    def invoke_tools(self, request: LLMToolRequest) -> LLMToolResponse: ...


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
            self._request_endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urlopen(http_request, timeout=self.profile.timeout_seconds, context=self._ssl_context()) as response:  # noqa: S310 - operator-configured endpoint
                body = json.loads(response.read().decode("utf-8"))
            content = self._content(body)
            parsed = json.loads(content) if isinstance(content, str) else content
            output = response_model.model_validate(parsed)
        except HTTPError as exc:
            raise LLMProviderError(f"Structured LLM call failed: HTTP {exc.code}") from exc
        except URLError as exc:
            raise LLMProviderError("Structured LLM call failed: network_unreachable") from exc
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

    def invoke_tools(self, request: LLMToolRequest) -> LLMToolResponse:
        """Run one native tool-calling turn.

        Each supported protocol uses its native function/tool representation.
        We deliberately never emulate a function call by asking a model to
        produce JSON in free-form text: unsupported protocols fail closed and
        the deterministic research orchestrator remains available.
        """
        if self.profile.protocol not in {
            "openai_compatible", "anthropic_messages", "gemini_generate_content", "ollama",
        }:
            raise LLMProviderError("Provider profile does not support native function calling")
        if not self.profile.endpoint:
            raise LLMProviderError("Provider endpoint is required")
        self._validate_runtime_endpoint()
        started = time.perf_counter()
        payload, headers = self._tool_payload(request)
        http_request = Request(
            self._request_endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urlopen(http_request, timeout=self.profile.timeout_seconds, context=self._ssl_context()) as response:  # noqa: S310 - operator-configured endpoint
                body = json.loads(response.read().decode("utf-8"))
            calls, content = self._tool_response(body)
        except HTTPError as exc:
            raise LLMProviderError(f"Function-call LLM request failed: HTTP {exc.code}") from exc
        except URLError as exc:
            raise LLMProviderError("Function-call LLM request failed: network_unreachable") from exc
        except Exception as exc:
            raise LLMProviderError(f"Function-call LLM request failed: {type(exc).__name__}") from exc
        return LLMToolResponse(
            tool_calls=calls,
            content=content,
            provider_protocol=self.profile.protocol,
            model=self.profile.model,
            input_tokens=self._usage(body, "input", _token_estimate(payload)),
            output_tokens=self._usage(body, "output", _token_estimate({"calls": [call.model_dump() for call in calls], "content": content})),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response={"id": body.get("id"), "model": body.get("model"), "tool_call_count": len(calls)},
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
        if self.profile.protocol == "gemini_generate_content":
            if self.api_key:
                headers["x-goog-api-key"] = self.api_key
                headers.pop("Authorization", None)
            return {
                "systemInstruction": {"parts": [{"text": request.system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": json.dumps(request.user_payload, ensure_ascii=False)}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": request.response_schema,
                    "maxOutputTokens": request.max_output_tokens,
                },
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
        # Poe's Chat Completions endpoint accepts the OpenAI request shape but
        # some hosted models do not enforce ``response_format.json_schema``.
        # Include the schema in the prompt as well, so those models still know
        # the exact field contract instead of returning a generic {"answer": …}.
        schema_prompt = (
            f"{request.system_prompt}\n\n"
            "Return exactly one JSON object, with no markdown fence or extra keys, "
            "that validates against this schema:\n"
            f"{json.dumps(request.response_schema, ensure_ascii=False)}"
        )
        return {
            "model": self.profile.model,
            "messages": [
                {"role": "system", "content": schema_prompt},
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
        if self.profile.protocol == "gemini_generate_content":
            candidates = body.get("candidates") or []
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        return body.get("choices", [])[0]["message"]["content"]  # type: ignore[index]

    def _tool_payload(self, request: LLMToolRequest) -> tuple[dict[str, object], dict[str, str]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        messages = [{"role": "system", "content": request.system_prompt}, *request.messages]
        if self.profile.protocol == "openai_compatible":
            return {
                "model": self.profile.model, "messages": messages,
                "tools": [{"type": "function", "function": tool.model_dump(mode="json")} for tool in request.tools],
                "tool_choice": "auto", "parallel_tool_calls": False, "max_tokens": request.max_output_tokens,
            }, headers
        if self.profile.protocol == "anthropic_messages":
            if self.api_key:
                headers.pop("Authorization", None)
                headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = "2023-06-01"
            return {
                "model": self.profile.model, "system": request.system_prompt,
                "messages": self._anthropic_messages(request.messages),
                "tools": [{"name": tool.name, "description": tool.description, "input_schema": tool.parameters} for tool in request.tools],
                "max_tokens": request.max_output_tokens,
            }, headers
        if self.profile.protocol == "gemini_generate_content":
            if self.api_key:
                headers.pop("Authorization", None)
                headers["x-goog-api-key"] = self.api_key
            return {
                "systemInstruction": {"parts": [{"text": request.system_prompt}]},
                "contents": self._gemini_messages(request.messages),
                "tools": [{"functionDeclarations": [tool.model_dump(mode="json") for tool in request.tools]}],
                "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
                "generationConfig": {"maxOutputTokens": request.max_output_tokens},
            }, headers
        # Ollama `/api/chat` supports native tools, including local models.
        return {
            "model": self.profile.model, "stream": False, "messages": messages,
            "tools": [{"type": "function", "function": tool.model_dump(mode="json")} for tool in request.tools],
            "options": {"num_predict": request.max_output_tokens},
        }, headers

    @staticmethod
    def _gemini_content(message: dict[str, object]) -> dict[str, object]:
        role = "model" if message.get("role") == "assistant" else "user"
        content = message.get("content", "")
        return {"role": role, "parts": [{"text": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)}]}

    @staticmethod
    def _anthropic_messages(messages: list[dict[str, object]]) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for message in messages:
            role = message.get("role")
            if role == "system":
                continue
            if role == "assistant" and isinstance(message.get("tool_calls"), list):
                blocks = []
                for call in message["tool_calls"]:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function") or {}
                    raw = function.get("arguments", "{}") if isinstance(function, dict) else "{}"
                    arguments = json.loads(raw) if isinstance(raw, str) else raw
                    blocks.append({"type": "tool_use", "id": str(call.get("id") or ""), "name": str(function.get("name") or ""), "input": arguments if isinstance(arguments, dict) else {}})
                result.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                result.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": str(message.get("tool_call_id") or ""), "content": str(message.get("content") or "")} ]})
            else:
                result.append({"role": "assistant" if role == "assistant" else "user", "content": str(message.get("content") or "")})
        return result or [{"role": "user", "content": "Please use the supplied research tools."}]

    @classmethod
    def _gemini_messages(cls, messages: list[dict[str, object]]) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for message in messages:
            role = message.get("role")
            if role == "system":
                continue
            if role == "assistant" and isinstance(message.get("tool_calls"), list):
                parts = []
                for call in message["tool_calls"]:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function") or {}
                    raw = function.get("arguments", "{}") if isinstance(function, dict) else "{}"
                    arguments = json.loads(raw) if isinstance(raw, str) else raw
                    parts.append({"functionCall": {"name": str(function.get("name") or ""), "args": arguments if isinstance(arguments, dict) else {}}})
                result.append({"role": "model", "parts": parts})
            elif role == "tool":
                try:
                    response = json.loads(str(message.get("content") or "{}"))
                except ValueError:
                    response = {"text": str(message.get("content") or "")}
                result.append({"role": "user", "parts": [{"functionResponse": {"name": str(message.get("name") or "research_tool"), "response": response}}]})
            else:
                result.append(cls._gemini_content(message))
        return result or [{"role": "user", "parts": [{"text": "Please use the supplied research tools."}]}]

    def _tool_response(self, body: dict[str, object]) -> tuple[list[LLMToolInvocation], str | None]:
        if self.profile.protocol == "anthropic_messages":
            blocks = body.get("content") or []
            calls = [
                LLMToolInvocation(id=str(item.get("id") or ""), name=str(item.get("name") or ""), arguments=dict(item.get("input") or {}))
                for item in blocks if isinstance(item, dict) and item.get("type") == "tool_use"
            ]
            text = "\n".join(str(item.get("text", "")) for item in blocks if isinstance(item, dict) and item.get("type") == "text") or None
            return calls, text
        if self.profile.protocol == "gemini_generate_content":
            candidates = body.get("candidates") or []
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            calls = []
            text_parts = []
            for index, item in enumerate(parts):
                if not isinstance(item, dict):
                    continue
                function = item.get("functionCall") or {}
                if function:
                    arguments = function.get("args") or {}
                    if not isinstance(arguments, dict):
                        raise ValueError("Gemini function arguments must be an object")
                    calls.append(LLMToolInvocation(id=f"gemini-{index}", name=str(function.get("name") or ""), arguments=arguments))
                if isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
            return calls, "\n".join(text_parts) or None
        if self.profile.protocol == "ollama":
            message = body.get("message") or {}
            raw_calls = message.get("tool_calls") or [] if isinstance(message, dict) else []
            content = message.get("content") if isinstance(message, dict) else None
        else:
            choices = body.get("choices") or []
            message = choices[0].get("message", {}) if choices else {}
            raw_calls = message.get("tool_calls") or [] if isinstance(message, dict) else []
            content = message.get("content") if isinstance(message, dict) else None
        calls: list[LLMToolInvocation] = []
        for index, item in enumerate(raw_calls):
            function = item.get("function") or {} if isinstance(item, dict) else {}
            raw_arguments: Any = function.get("arguments", "{}")
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            if not isinstance(arguments, dict):
                raise ValueError("Function arguments must be an object")
            calls.append(LLMToolInvocation(id=str(item.get("id") or f"tool-{index}"), name=str(function.get("name") or ""), arguments=arguments))
        return calls, content if isinstance(content, str) else None

    def _usage(self, body: dict[str, object], direction: str, fallback: int) -> int:
        usage = body.get("usage") or body.get("usageMetadata") or {}
        if not isinstance(usage, dict):
            return fallback
        keys = ("prompt_tokens", "input_tokens", "promptTokenCount") if direction == "input" else ("completion_tokens", "output_tokens", "candidatesTokenCount")
        for key in keys:
            if usage.get(key) is not None:
                return int(usage[key])
        return fallback

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

    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        """Use the operating-system CA bundle without disabling TLS checks.

        Desktop development commonly routes HTTPS through a local proxy.  The
        bundled Python certificate set may not include that proxy's trusted
        root while macOS' system bundle does.  Prefer an explicit user bundle,
        then the system bundle; certificate verification always remains on.
        """
        candidates = (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/cert.pem")
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return ssl.create_default_context(cafile=candidate)
        return ssl.create_default_context()

    def _request_endpoint(self) -> str:
        """Return the concrete HTTP endpoint expected by the selected protocol.

        Most OpenAI-compatible providers document their base URL as ``.../v1``.
        The UI accepts that convenient form and completes the standard chat
        endpoint here, while preserving explicit endpoints supplied by users.
        """
        endpoint = (self.profile.endpoint or "").rstrip("/")
        if self.profile.protocol == "openai_compatible" and endpoint.endswith("/v1"):
            return f"{endpoint}/chat/completions"
        return endpoint


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
                "applicable_horizon": "20-session risk observation",
                "current_assessment": "Only the evidence-bound risk observation can be stated.",
                "reasoning": ["The conclusion is limited by the frozen evidence and quality gate."],
                "major_risks": ["Conflicting or stale evidence can weaken the conclusion."],
                "invalidation_conditions": ["Refresh or withdraw the observation after material new disclosures."],
                "data_as_of": request.user_payload.get("data_as_of"),
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

    def invoke_tools(self, request: LLMToolRequest) -> LLMToolResponse:
        # Mock mode must never present fabricated model reasoning as a real
        # function-call decision.  The orchestrator will take its documented
        # deterministic path when no user-configured provider is available.
        return LLMToolResponse(
            provider_protocol="mock",
            model=self.profile.model,
            input_tokens=_token_estimate(request.messages),
            output_tokens=0,
            latency_ms=0,
        )


def build_llm_provider(profile: ProviderProfile, api_key: str | None = None) -> LLMProvider:
    if profile.protocol == "mock":
        return MockProvider(profile)
    return HTTPStructuredProvider(profile, api_key=api_key)
