# Run Bundle Storage Operations

Run bundles now support storage operations beyond static reports:

- retention job execution
- artifact integrity verification
- downloadable run bundle archive

These operations use the existing run bundle manifest and registry paths as the source of truth.

## Multi-Worker Persistence

Run bundle persistence is safe for CI workers that write different runs into the same output root:

- Bundle files use a per-run writer lock, so two writers cannot mutate the same run directory at once.
- Different run IDs can write artifacts, evidence, registries, and reports in parallel.
- The shared SQLite audit database uses a separate audit writer lock plus SQLite `busy_timeout` to serialize short audit commits.
- The shared `history.json` index uses a separate history writer lock around previous-run lookup, comparison report creation, and index update.

This keeps worker-local artifact generation concurrent while protecting the shared audit and history indexes from lost writes.

## Retention Job

Endpoint:

- `POST /api/v1/test-officer/runs/{run_id}/retention-job`

Query parameters:

- `apply=false`: dry-run mode; reports what would happen.
- `apply=true`: executes eligible delete/archive candidates.
- `now=<iso-time>`: optional clock override for deterministic CI tests.

Behavior:

- `retain` and protected candidates are never deleted.
- `delete-after-retention` removes expired files only when `apply=true`.
- `archive-after-retention` writes a zip under `archives/retention/` and removes the original only when `apply=true`.
- Candidate paths are resolved inside the run root, so a retention plan cannot delete files outside the run bundle.
- The result is written to `reports/retention-job.json`.

## Artifact Integrity

Endpoint:

- `POST /api/v1/test-officer/runs/{run_id}/integrity`

Behavior:

- Reads artifacts from `manifest.artifacts`.
- Computes actual SHA-256 and size.
- Compares against manifest `sha256` and `sizeBytes` when present.
- Writes `reports/integrity-report.json`.

This makes artifact corruption, missing screenshots, and trace/video truncation visible to CI and Workbench.

## Artifact Encryption

Run bundle persistence can encrypt artifact files at rest with AES-256-GCM.

Configuration:

- `AI_TEST_OFFICER_ARTIFACT_ENCRYPTION_KEY`: 32-byte key as `base64:<value>`, plain base64, 64-character hex, or a raw 32-byte string.
- `AI_TEST_OFFICER_ARTIFACT_ENCRYPTION_KEY_REF`: optional key reference recorded in manifest metadata.

Behavior:

- Artifact files under `artifacts/` are written as ciphertext when a key is configured.
- `manifest.artifacts[].sha256` and `sizeBytes` describe the stored ciphertext, so integrity checks still verify bytes on disk.
- `manifest.artifacts[].metadata.plaintextSha256` and `plaintextSizeBytes` describe the decrypted artifact for API verification.
- Inline artifact previews are withheld for encrypted artifacts instead of duplicating plaintext into the manifest.
- `GET /api/v1/test-officer/runs/{run_id}/artifacts/{artifact_name}` decrypts into a temporary response file only when the matching key is configured.
- Missing or mismatched encryption keys fail closed with `503`; encrypted artifacts are not silently served as ciphertext.
- Download bundles include ciphertext artifact files plus manifest metadata, so the bundle remains encrypted at rest and can be decrypted by a holder of the configured key.

## Download Bundle

Endpoints:

- `POST /api/v1/test-officer/runs/{run_id}/download-bundle`
- `GET /api/v1/test-officer/runs/{run_id}/download-bundle`

Behavior:

- Creates `reports/run-bundle.zip`.
- Writes `reports/download-manifest.json`.
- Includes manifest, registry, evidence, artifacts, and reports currently present in the run root.
- Large Playwright trace/video files can be kept out of the zip while still being listed in `download-manifest.json`.

The `GET` endpoint returns the zip with run access checks, so CI can archive a single bundle and Workbench can expose a complete downloadable evidence packet.

Large artifact controls:

- `AI_TEST_OFFICER_DOWNLOAD_LARGE_ARTIFACT_BYTES`: threshold for trace/video payloads, default `104857600`.
- `AI_TEST_OFFICER_DOWNLOAD_LARGE_ARTIFACT_STRATEGY=include`: default behavior; large trace/video files are zipped.
- `AI_TEST_OFFICER_DOWNLOAD_LARGE_ARTIFACT_STRATEGY=reference-only`: large trace/video files are omitted from `run-bundle.zip`, but the download manifest records `included=false`, `largeArtifact=true`, `artifactId`, `artifactKind`, size, path, strategy, and reason.

Persisted run bundle artifacts also carry manifest metadata for runtime traces/videos:

- `runtimeArtifact`
- `storageClass`
- `largeArtifact`
- `largeArtifactThresholdBytes`
- `recommendedRetentionAction`
- `recommendedDownloadStrategy`

## Access Control

The new JSON reports are treated as sensitive reports:

- `retention-job.json`
- `integrity-report.json`
- `download-manifest.json`

They require agent or run-scoped access and are not exposed through public signed report URLs.
