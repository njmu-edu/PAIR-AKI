# Integration Standards

English | [简体中文](INTEGRATION.zh-CN.md) · [Project](README.md)

## Application API v2

Base path: `/api/competition/v2`. Requests and responses use UTF-8 JSON. The Python reference service listens on loopback. JSON Schema descriptions are in [`schemas/`](schemas/); runtime checks remain authoritative.

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/capabilities` | Actual coordinator/provider modes, model IDs, budgets, and source identity |
| GET | `/cases` | Registered synthetic case snapshots |
| GET | `/cases/{case_ref}` | One evaluation-time snapshot |
| POST | `/runs` | Start one bounded task; returns HTTP 202 and `run_id` |
| GET | `/runs/{run_id}` | Read status, ordered events, and terminal result |

### Start a task

```json
{
  "goal": "Only predict the first qualifying creatinine event within the next 24 hours.",
  "case_ref": "ae-201",
  "snapshot_ref": "<copy the exact snapshot_ref from GET /cases>",
  "mode": "autonomous"
}
```

`mode` is `autonomous`, `general`, or `fixed`. The goal is the user's request, not a hidden expected tool route. Arbitrary patient fields, SQL, filesystem paths, and model URLs are not accepted in this request.

Read the returned run ID until status leaves `queued` or `running`. Terminal states are `succeeded`, `partial`, `blocked`, `needs_clarification`, and `failed`. Re-reading a run never resubmits it.

### Successful prediction shape

```json
{
  "label": 1,
  "receipt": {
    "role": "M_P",
    "mode": "trained",
    "model_id": "your-predictor-id",
    "contract_version": "mp-binary-v1",
    "input_sha256": "<accepted snapshot SHA-256>",
    "bundle_sha256": "<registered model-bundle SHA-256>"
  }
}
```

Only the label is a business decision. A missing result, failed call, or blocked input does not produce label `0`. Model scores, logits, calibration values, and probabilities are rejected at the business/coordination boundary.

The full result includes `prediction`, `comparables`, `narrative`, `evidence`, `limitations`, `final_snapshot`, metrics, versions, and termination details. An AGH-mediated result additionally includes `execution_runtime` with session ID, inner run ID, stage list, ledger SHA, and outer runtime costs.

### Input standards

- Evaluation timestamps use ISO 8601. Observation `event_hours` and `available_hours` are relative to the evaluation time, with future input prohibited.
- Serum creatinine units are explicit. Supported conversion logic normalizes compatible values; conflicting or unknown values are not imputed as normal.
- The endpoint and snapshot version must match the model's support signature. The target is a first qualifying creatinine event, not full clinical AKI diagnosis.
- Case references, patient/admission references, source kind, source references, and hashes remain distinct identities.
- The public server's source is `synthetic`. Hospital-source adapters and ingestion endpoints are not part of this release.

## Coordinator integration

The coordinator consumes `/chat/completions` under a configured local OpenAI-compatible `/v1` base URL. It must support non-streaming JSON Schema responses and report the exact configured model ID. Candidate plans are checked again by Python; structured generation does not replace runtime validation.

```sh
export PAIR_AKI_MODEL_URL=http://127.0.0.1:8000/v1
export PAIR_AKI_MODEL=your-served-model-id
# Optional local-service credential: PAIR_AKI_MODEL_API_KEY
python3 -m pair_aki.server --state-dir "$HOME/.local/state/pair-aki/live" --synthetic-medical
```

Only explicitly supplied local endpoints are used. Redirects and proxy-environment routing are disabled. Credentials are not included in saved model-request receipts.

## Medical provider integration

The standard-library client in `pair_aki/medical_provider.py` supports two separately hosted endpoints. It does not load private training artifacts or convert arbitrary model responses into decisions.

| Endpoint | Request | Response |
| --- | --- | --- |
| GET `/identity` | None | `role`, `mode: trained`, `model_id`, `bundle_sha256`, and `support_signature` |
| POST `/predict` | `{"states": [snapshot]}` | `{"label": 0 or 1, "receipt": ...}` for `M_P` |
| POST `/compare` | `{"states": [query, candidate_a, candidate_b]}` | `{"choice": "A" or "B", "margin": finite number, "receipt": ...}` for `M_R` |

A support signature contains `version: specialist-support-v1`, `role`, `cohort_id`, `population_id`, `snapshot_version`, `endpoint`, `age_days_min`, and `age_days_max`. The endpoint identity is checked before each medical call. Receipts bind `M_P` to `input_sha256`, and `M_R` to `query_sha256`, `left_sha256`, and `right_sha256`, together with role, mode, model, contract, and bundle identity.

`M_R.margin` is an internal pairwise decision value used for order aggregation and private audit. It is removed from business reports and never interpreted as clinical probability. The engine verifies that `choice` agrees with its sign.

```sh
export PAIR_AKI_PREDICTOR_URL=http://127.0.0.1:8001
export PAIR_AKI_RERANKER_URL=http://127.0.0.1:8002
python3 -m pair_aki.server --state-dir "$HOME/.local/state/pair-aki/trained"
```

Trained providers must be supplied by the operator. This repository supplies no model weights and makes no automatic fallback to synthetic providers. It accepts only the built-in synthetic case source.

## Run through AGH

The adapter targets the audited official AGH revision **`4bc36bc4c4441206388a53bece17379c1d7be14d`**. Current upstream APIs may differ. The adapter intentionally pins this revision instead of claiming compatibility with the latest upstream.

Prepare Node.js 24.10+, Python 3.11+, Git, and a local coordinator. Run from the repository root:

```sh
export PAIR_AKI_AGH_UPSTREAM="$HOME/.cache/pair-aki/agh-source"
# Use a new directory. Existing source checkouts are preserved.
sh agh/prepare.sh
(cd agh && npm ci --ignore-scripts && npm run build)
```

`agh/build.mjs` verifies the pinned manifest and each file in the audited dependency closure before bundling the original Kernel. Upstream is a separate checkout and is not copied into this repository.

Start the inner server with a live coordinator. For a synthetic medical demonstration:

```sh
export PAIR_AKI_MODEL_URL=http://127.0.0.1:8000/v1
export PAIR_AKI_MODEL=your-served-model-id
python3 -m pair_aki.server --state-dir "$HOME/.local/state/pair-aki/inner" --synthetic-medical
```

In a second terminal, use the same model configuration and start the AGH gateway:

```sh
export PAIR_AKI_ALLOW_SYNTHETIC=1
# Explicitly authorizes synthetic medical providers; it does not relabel them as trained.
python3 -m pair_aki.compat.gateway \
  --state "$HOME/.local/state/pair-aki/agh" \
  --node "$(command -v node)" --runner "$PWD/agh/dist/runner.mjs" \
  --api-url http://127.0.0.1:30886 \
  --llm-url "$PAIR_AKI_MODEL_URL" --port 30888
```

Then submit through AGH:

```sh
python3 -m pair_aki.cli --api http://127.0.0.1:30888 \
  --goal 'Combined assessment: predict the 24-hour event and retrieve comparable cases.'
```

For the Vite workbench, set `PAIR_AKI_API_TARGET=http://127.0.0.1:30888` in the environment before `make web-dev`, or copy `.env.example` to a local untracked `.env` and set it there. Direct requests to port 30886 exercise the inner agent; requests through 30888 exercise the AGH chain. Keep this distinction in recordings and comparisons.

### Three actual stages

1. `admit_case`: read the case and current model identities.
2. `execute_assessment`: submit the unchanged goal and await the application's real terminal state.
3. `verify_assessment`: re-read and verify the bound result, then preserve its actual status.

A normal completed session has three matched `tool/call` and `tool/result` pairs in the native AGH ledger. Do not use a preflight, printed stage names, or a scripted quick start as evidence of this chain.

## Execution records

The gateway state directory contains:

```text
agh/<application-run-id>/<agh-session-id>/
  kernel-ledger.json
  provider-receipts.json
  tool-trace.jsonl
  run-receipt.json
  verified-result.json
```

Inner run IDs and AGH session IDs are different. Preserve both, event sequence, tool-use IDs, actual model identity/mode, failures, cost counts, and the ledger hash. Store original records outside the source checkout. If publishing a redacted copy, identify it as modified, preserve original-file hashes as provenance, and calculate a separate hash for the exported file.

The state directory uses an exclusive service lease. Interrupted tasks remain failed records after recovery; an ambiguous inner submission is not automatically repeated. A failed or partial medical task must not be described as a successful clinical assessment merely because outer execution completed.
