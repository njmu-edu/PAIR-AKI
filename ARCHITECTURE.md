# Architecture

English | [简体中文](ARCHITECTURE.zh-CN.md) · [Project](README.md)

## Responsibilities

PAIR-AKI separates application execution from medical decision models.

| Layer | Makes decisions about | Enforces |
| --- | --- | --- |
| AGH runtime | Which outer application stage to execute next, using a live coordinator | Registered tools, stage dependencies, native session history, and completion evidence |
| Qwen coordinator | The user's requested outcomes, short medical-tool plans, evidence acquisition, clarification, and proposed stopping | Its proposals remain subject to the medical harness |
| Medical harness | Whether an action is permitted and whether its result is admissible | Case/time identity, source eligibility, model contracts, atomic updates, budgets, and references |
| `M_P` | Native candidates `0/1` | Provider identity and receipt contract |
| `M_R` | Native candidates `A/B` for a query and two reference patients | Distinct-patient and pair-input contract |

The public source adapts the competition core to portable model endpoints. It does not contain private training data, adapters, deployment registries, or internal documents. The transport checks the configured served model ID; this is not a claim that an arbitrary external service's weights have been independently audited.

## Snapshot representation

A snapshot binds a patient/admission reference to one evaluation time. It carries observation time and availability offsets, measurement units, provenance references, missing/conflicted status, and the endpoint/version identity. The public repository constructs only synthetic snapshots.

A missing or conflicting value is not treated as a normal measurement. Prediction and comparison have separate eligibility checks. Predictions use only information available at the evaluation time; future follow-up is a label-construction concern, not a prediction-time input.

## Inner agent loop

1. Validate the requested case and snapshot identity.
2. Ask the coordinator to interpret the goal. No expected route or evaluation answer is supplied.
3. Present accepted facts, available source metadata, and actual tool feedback.
4. Let the coordinator propose a short plan, a clarification, or a finish action.
5. Validate permissions and budgets before each action. Rebind queued work to the latest accepted snapshot.
6. Build a report from verified tool results. Stop on satisfied postconditions, a supported boundary, failure, or budget exhaustion.

The engine supports `autonomous`, `general`, and `fixed` modes for controlled engineering comparisons. A fixed flow shares the same capability contracts and budgets. The scripted quick start is a labelled test fixture; it does not demonstrate LLM autonomy.

### Evidence updates

Evidence acquisition operates on a candidate copy. The acquisition tool validates case identity, admission, evaluation time, immutable historical observations, and source permissions before accepting a new snapshot. A failure leaves the current state unchanged. An accepted update invalidates predictions and comparisons tied to the previous input hash.

### Stopping and failure

Default inner budgets are 240 seconds, 6 tool calls, 8 coordinator calls, and 2 corrections. Medical-model forwards are counted separately. Terminal states are immutable. Restarting the same state directory records interrupted work as failed and does not automatically replay a medical request.

The engine may end a run when independently checked postconditions are met. The termination receipt distinguishes this from a coordinator-authored finish. Valid tool execution does not by itself establish that the coordinator interpreted the user's goal correctly or that a medical prediction is correct.

## Two finite-candidate medical models

The research implementation uses two separately trained Qwen3.5-4B models. “Jev-like” here means **case state + task question + finite candidates + native candidate-score readout**, trained with supervised cross-entropy. It is not an official Jev or RLCD reproduction.

- `M_P`: selects `0` or `1` for the study-defined 24-hour first qualifying creatinine event. A tie selects `1`. No probability threshold search or calibration is required by the binary business interface.
- `M_R`: compares candidate A and B. Structured recall considers age/course timing, creatinine state, and past trends. Each pair is compared in both presentation orders; combined preference contributes to a deterministic win score. Ties fall back to the structured score and stable case reference. Up to 12 reference patients imply up to 132 pairwise forwards.

The reference index uses eligible training/reference states, excludes every admission of the query patient, and returns one selected time point per reference patient. Future outcomes do not enter recall, ranking inputs, or rule-generated preference labels. Similarity is an engineering comparison, not a diagnosis or treatment-effect probability.

Private weights and hospital datasets are not shipped. The public `MedicalEndpoint` connects to services following the published contract. Synthetic providers exercise the same interface and remain explicitly marked as synthetic.

## AGH execution

The pinned official Kernel runs three dependent tools:

| Tool | Real operation | Evidence |
| --- | --- | --- |
| `admit_case` | Read the current capability identity and selected snapshot | Input and capability receipt |
| `execute_assessment` | Submit the unchanged user goal to the inner agent and wait for its actual terminal state | Application run ID and terminal-record hash |
| `verify_assessment` | Re-read the run, verify binding, binary result, model receipts, patient exclusion, and references | Verified result and original terminal status |

Completed stages cannot be replayed automatically. A submission-intent file is created before the inner POST; an ambiguous outcome cannot trigger a second medical submission. Kernel failure does not silently fall back to a direct API call.

Each session writes `kernel-ledger.json`, `provider-receipts.json`, `tool-trace.jsonl`, and `run-receipt.json` outside the source tree. The AGH session and inner application run are distinct IDs. Both layers' coordinator calls and elapsed times are accounted for. Redacted exports must disclose modifications and keep original-file hashes separate from export-file hashes.

## Workbench

React/TypeScript/Vite provides prediction, retrieval, and combined task entry points. The frontend submits the natural-language goal and references; it does not calculate medical outputs. The evidence drawer exposes steps, receipts, source versions, and limitations. Loading, failed, blocked, partial, clarification, and saved-run states remain visible.

The reference API listens on loopback, accepts registered synthetic case references only, and exposes no raw patient upload, database access, or shell tool. An external deployment needs its own reviewed access and resource controls.
