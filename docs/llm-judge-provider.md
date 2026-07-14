# LLM Judge Provider Contract

The platform can run with a deterministic judge only, a fixture-backed strict LLM response, or a generic HTTP LLM judge provider.

## Modes

Deterministic baseline only:

```bash
HEADLESS=1 npm run commit-check
```

Fixture-backed strict LLM response for tests and demos:

```bash
LLM_JUDGE_RESPONSE_PATH=./fixtures/judge-response.json HEADLESS=1 npm run commit-check
```

HTTP provider:

```bash
LLM_JUDGE_ENDPOINT=http://127.0.0.1:9000/judge \
LLM_JUDGE_API_KEY=<token> \
LLM_JUDGE_MODEL=<model-name> \
LLM_JUDGE_TIMEOUT_MS=10000 \
HEADLESS=1 npm run commit-check
```

The same provider variables can also use the `AI_TEST_OFFICER_` prefix:

- `AI_TEST_OFFICER_LLM_JUDGE_ENDPOINT`
- `AI_TEST_OFFICER_LLM_JUDGE_API_KEY`
- `AI_TEST_OFFICER_LLM_JUDGE_MODEL`
- `AI_TEST_OFFICER_LLM_JUDGE_TIMEOUT_MS`

`LLM_JUDGE_RESPONSE` and `LLM_JUDGE_RESPONSE_PATH` take precedence over HTTP provider variables so deterministic tests stay reproducible.

## Request Shape

The provider receives one `POST` request with JSON:

```json
{
  "schemaVersion": "ai-test-officer.llm-judge-request.v1",
  "model": "judge-model",
  "prompt": {
    "system": "trusted judge policy and boundary rules",
    "user": "trusted policy, untrusted requirement/diff, observed facts, machine evidence"
  },
  "run": {
    "runId": "run_x",
    "missionId": "mission_x",
    "evidenceCount": 3
  },
  "allowedEvidenceIds": ["evidence_1"],
  "responseFormat": {
    "type": "strict-json",
    "schemaName": "StrictLlmJudgeResponse",
    "requiredEvidenceRefs": true
  }
}
```

The platform sends only structured prompt text and evidence IDs. It does not send API keys, cookies, raw browser storage, or full artifact files to the provider.

## Accepted Responses

The safest response is direct strict judge JSON:

```json
{
  "decision": "fail",
  "confidence": 0.82,
  "summary": "The release is blocked by evidence.",
  "evidenceRefs": ["evidence_1"],
  "findings": [
    {
      "title": "Completed filter failed",
      "category": "product-bug",
      "severity": "high",
      "summary": "The assertion evidence shows the expected state was not reached.",
      "evidenceRefs": ["evidence_1"]
    }
  ]
}
```

The provider may also wrap that JSON string in `content`, `output`, `text`, or `choices[0].message.content`.

## Failure Behavior

The strict judge parser fails closed:

- non-JSON output falls back to the deterministic baseline
- missing `evidenceRefs` falls back to the deterministic baseline
- unknown evidence IDs fall back to the deterministic baseline
- provider timeout or HTTP error falls back to the deterministic baseline

When fallback happens, the report metadata records:

```json
{
  "source": "strict_llm_judge",
  "executionMode": "fallback-baseline",
  "llmStatus": "failed",
  "llmError": "..."
}
```

This keeps model outages visible without turning the quality gate into an uncontrolled failure mode.
