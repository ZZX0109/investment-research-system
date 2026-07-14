# AI Test Officer implementation boundary

`ai-test-officer/` is the only supported product implementation. The root investment-research project now consumes its versioned HTTP API or official npm CLI through `src/ai_test_officer_client.ts`.

The former `src/platform` implementation and its generated `dist/platform` output have been removed. Root regression and preview integrations call the official API/CLI only. Imported historical evidence is treated as `legacy-unverified` and cannot satisfy a production gate.
