"""Natural-language intent, model-selected tools, independently enforced execution."""
from __future__ import annotations
import copy
import re
import time
from pair_aki.backend.domain import ContractError
from pair_aki.backend.tool_contracts import acquire_evidence, failure
from pair_aki.backend.narrative import verify_references
from .state import Budget, TOOLS, OUTCOME_TOOL, VERSION, factual_view, require_no_model_scores, validate_interpretation
from .medical import MedicalTools
from .completion import terminal_postconditions
from .plans import PlanQueue
from .report import build as build_report


class RunBudget(Exception):
    pass


def compact_feedback(tool, value):
    row = {"tool": tool, "status": value["status"]}
    for key in ("reason", "admission", "medical_admission", "error", "snapshot_ref", "available_sources", "source_catalog"):
        if key in value:
            row[key] = value[key]
    if "prediction" in value:
        row["prediction"] = value["prediction"]
    if "comparables" in value:
        result = value["comparables"]
        row["comparables"] = {"status": result["status"], "reason": result["reason"], "index_sha256": result["index_sha256"],
                              "matches": [{k: m[k] for k in ("case_ref", "snapshot_ref", "rank", "coverage", "similarities", "differences", "missing")}
                                          for m in result["matches"]]}
    return row


class Engine:
    version = "autonomous-agent-v10.1"

    def __init__(self, repository, index, predictor, comparator, ledger, coordinator, budget=Budget()):
        self.repository, self.index, self.ledger = repository, index, ledger
        self.coordinator, self.budget = coordinator, budget
        self.medical = MedicalTools(repository, index, predictor, comparator, ledger)

    def validate_request(self, request):
        if not isinstance(request, dict) or set(request) != {"goal", "case_ref", "snapshot_ref", "mode"}:
            raise ContractError("v2_request_allowlist")
        if any(not isinstance(v, str) or not v.strip() for v in request.values()):
            raise ContractError("v2_request_field_types")
        if len(request["goal"]) > 2000 or request["mode"] not in {"autonomous", "general", "fixed"}:
            raise ContractError("v2_request_scope")
        if not re.fullmatch(r"[a-f0-9]{64}", request["snapshot_ref"]):
            raise ContractError("v2_explicit_snapshot_required")
        return self.repository.get(request["case_ref"], request["snapshot_ref"])

    def execute(self, rid, request):
        state = self.validate_request(request)
        self.ledger.start(rid)
        started = time.monotonic()
        deadline = started + self.budget.seconds
        metrics = {"tool_calls": 0, "coordinator_calls": 0, "predictor_forwards": 0, "comparator_forwards": 0,
                   "medical_attempts": 0, "medical_forward_unknown": 0, "repairs": 0}
        handled, errors, attempts, seen, feedback = {}, {}, {}, set(), []
        auxiliary_errors = {}
        limits = []
        intent = {"outcomes": [], "clarification": None}
        stop = "incomplete"
        termination_origin = None
        clarification = None

        def event(kind, **fields):
            self.ledger.event(rid, {"kind": kind, **fields})

        plan_queue = PlanQueue(event)

        def remaining():
            return max(0, deadline - time.monotonic())

        def coordinate(phase, call):
            if remaining() <= 0 or metrics["coordinator_calls"] >= self.budget.coordinator:
                raise RunBudget()
            metrics["coordinator_calls"] += 1
            metadata = {"mode": self.coordinator.mode, "model_id": self.coordinator.model_id, "phase": phase}
            try:
                value, receipt = call(min(70, remaining()))
                audit = self.ledger.private_coordinator_audit(rid, {"phase": phase, "receipt": receipt, "output": value})
                event("coordinator_call", status="complete", details={**metadata, **audit, "output": value})
                return value
            except Exception as exc:
                receipt = getattr(exc, "receipt", None)
                audit = self.ledger.private_coordinator_audit(rid, {"phase": phase, "receipt": receipt, "error": failure(exc)})
                event("coordinator_call", status="failed", details={**metadata, **audit, "error": failure(exc)})
                raise

        event("snapshot", status="verified", details=factual_view(state))
        try:
            proposed_intent = coordinate("interpret", lambda timeout: self.coordinator.interpret(request["goal"], timeout=timeout))
            intent = validate_interpretation(proposed_intent)
            event("goal_interpretation", status="model_proposed", details=intent)
            if intent["clarification"] is not None:
                stop, clarification = "clarification", intent["clarification"]
            else:
                for _ in range(self.budget.tools + self.budget.repairs + 3):
                    if remaining() <= 0:
                        stop = "budget"
                        break
                    completed = terminal_postconditions(intent["outcomes"], handled, errors, auxiliary_errors,
                        state.snapshot_ref, self.repository.sources(state), seen, attempts)
                    if completed:
                        stop, termination_origin = completed["code"], completed["origin"]
                        event("goal_postconditions", status="verified", details=completed)
                        break
                    if request["mode"] == "fixed":
                        # Same model's interpretation; deterministic baseline uses actual source availability.
                        needed = [x for x in intent["outcomes"] if x not in handled and x not in errors]
                        if self.repository.sources(state) and ("get_evidence", state.snapshot_ref) not in seen:
                            tool = "get_evidence"
                        else:
                            tool = OUTCOME_TOOL[needed[0]] if needed else "finish"
                        action = {"tool": tool, "reason": "固定流程按模型解释与真实来源执行", "question": None, "clarification_kind": None}
                        event("fixed_action", status="selected", details=action)
                    elif plan_queue.pending:
                        action = plan_queue.pop(state)
                    else:
                        view = {"goal": request["goal"], "own_goal_interpretation": intent,
                                "state": factual_view(state), "available_sources": self.repository.sources(state),
                                "source_catalog": self.repository.source_catalog(state),
                                "verified_outcomes": {name: {"status": value["status"], "reason": value.get("reason"),
                                     "receipt_meaning": {"blocked": "工具已完成资格核验并签发受限依据；医学模型未调用，不是阴性。",
                                                         "failed": "工具已有真实失败回执，可报告失败或选择预算内重试。",
                                                         "complete": "工具已完成，结果已经核验。"}[value["status"]],
                                     "input_sha256": value.get("admission", {}).get("input_sha256", value.get("input_sha256"))}
                                     for name, value in {**handled, **errors}.items()},
                                "auxiliary_failures": copy.deepcopy(auxiliary_errors),
                                "feedback": feedback[-4:], "budget_remaining": {
                                    "tools": self.budget.tools - metrics["tool_calls"],
                                    "corrections": self.budget.repairs - metrics["repairs"]}}
                        require_no_model_scores(view)
                        if request["mode"] == "autonomous":
                            proposal = coordinate("plan", lambda timeout: self.coordinator.propose_plan(view, timeout=timeout))
                            action = plan_queue.load(proposal, state, intent["outcomes"])
                            if action is None:
                                action = plan_queue.pop(state)
                        else:
                            action = coordinate("plan", lambda timeout: self.coordinator.propose(
                                view, specialized=False, timeout=timeout))
                    if not isinstance(action, dict) or set(action) != {"tool", "reason", "question", "clarification_kind"}:
                        raise ContractError("action_schema")
                    tool = action["tool"]
                    if remaining() <= 0:
                        stop = "budget"
                        event("action_not_executed", tool=tool, status="budget", details={"reason": "deadline"})
                        break
                    if ((tool == "clarify" and action["clarification_kind"] not in {"goal", "permission", "case_or_time", "clinical_data"})
                            or (tool != "clarify" and action["clarification_kind"] is not None)):
                        raise ContractError("clarification_kind_schema")
                    outcome = next((key for key, value in OUTCOME_TOOL.items() if value == tool), None)
                    denial = None
                    if tool not in {*TOOLS, "finish", "clarify"}:
                        denial = "unknown_tool"
                    elif outcome and outcome not in intent["outcomes"]:
                        denial = "outside_interpreted_user_goal"
                    elif tool in TOOLS and (tool, state.snapshot_ref) in seen:
                        denial = "same_input_already_handled"
                    elif tool == "clarify" and action["clarification_kind"] == "clinical_data":
                        # This API binds case/time before execution and has no user data-upload
                        # channel. Intent clarification remains supported at the entry phase.
                        denial = "no_clinical_data_upload_channel"
                    elif tool == "clarify":
                        review = coordinate("plan", lambda timeout: self.coordinator.assess_clarification(
                            request["goal"], action, timeout=timeout))
                        if not review["necessary"]:
                            denial = "unnecessary_goal_reconfirmation"
                    elif tool == "finish":
                        if not auxiliary_errors and any(x not in handled and x not in errors for x in intent["outcomes"]):
                            denial = "missing_verified_task_evidence"
                        elif (not auxiliary_errors and self.repository.sources(state) and ("get_evidence", state.snapshot_ref) not in seen
                              and any(r["status"] == "blocked" for r in handled.values())):
                            denial = "accessible_evidence_not_exhausted"
                    if denial:
                        plan_queue.clear("action_rejected:" + denial)
                        explanation = {
                            "same_input_already_handled": "当前快照的该工具已有有效回执；重复调用不会增加证据，请使用已有回执。",
                            "no_clinical_data_upload_channel": "该提议要求补录临床资料，当前接口没有补录通道。可依据真实工具结果报告限制；目标、授权或病例时点歧义仍可澄清。",
                            "unnecessary_goal_reconfirmation": "目标复核认为问题仅重复确认已请求的任务；服务失败不取消其他已获请求的独立能力。请继续处理原目标并保留失败依据。",
                            "missing_verified_task_evidence": "用户目标中仍缺少实际处置回执的部分：" + ",".join(
                                x for x in intent["outcomes"] if x not in handled and x not in errors),
                            "accessible_evidence_not_exhausted": "已登记的资料来源尚未尝试，不能把尚未尝试描述成已查无资料。",
                        }.get(denial, "提议不满足本次任务权限或工具合同。")
                        rejection = {"reason": denial, "explanation": explanation}
                        event("tool_result", tool=tool, status="rejected", details=rejection)
                        feedback.append({"tool": tool, "status": "rejected", **rejection})
                        if metrics["repairs"] >= self.budget.repairs:
                            stop = "budget"
                            break
                        metrics["repairs"] += 1
                        continue
                    if tool == "clarify":
                        if not isinstance(action["question"], str) or not action["question"].strip():
                            raise ContractError("clarification_question_required")
                        stop, clarification = "clarification", action["question"]
                        break
                    if tool == "finish":
                        stop = "failed_tool" if errors or auxiliary_errors else "blocked_inputs" if any(r["status"] == "blocked" for r in handled.values()) else "completed"
                        termination_origin = "fixed_flow_finish" if request["mode"] == "fixed" else "coordinator_finish"
                        break
                    retrying = attempts.get((tool, state.snapshot_ref), 0) > 0
                    if (tool == "get_evidence" or retrying) and metrics["repairs"] >= self.budget.repairs:
                        stop = "budget"
                        event("action_not_executed", tool=tool, status="budget", details={"reason": "corrections"})
                        break
                    if metrics["tool_calls"] >= self.budget.tools:
                        stop = "budget"
                        event("action_not_executed", tool=tool, status="budget", details={"reason": "tools"})
                        break
                    metrics["tool_calls"] += 1
                    if retrying and tool != "get_evidence":
                        metrics["repairs"] += 1
                    input_sha = state.snapshot_ref
                    event("tool_start", tool=tool, status="running", details={"input_sha256": input_sha})
                    try:
                        if tool == "read_case_state":
                            value = {"status": "complete", "state": factual_view(state), "snapshot_ref": state.snapshot_ref,
                                     "medical_admission": self.medical.inspect_admissions(state),
                                     "source_catalog": self.repository.source_catalog(state),
                                     "available_sources": self.repository.sources(state)}
                        elif tool == "get_evidence":
                            metrics["repairs"] += 1
                            candidate = acquire_evidence(self.repository, state)
                            checked = self.medical.inspect_admissions(candidate)
                            changed = candidate.snapshot_ref != input_sha
                            # Prepare the full receipt before accepting the new input.
                            # Metadata/qualification failures must preserve prior facts/results.
                            value = {"status": "complete" if changed else "no_new_evidence", "state": factual_view(candidate),
                                     "medical_admission": checked,
                                     "source_catalog": self.repository.source_catalog(candidate),
                                     "snapshot_ref": candidate.snapshot_ref, "available_sources": self.repository.sources(candidate)}
                            if changed:
                                old_results = sorted(set(handled) | set(errors))
                                event("results_invalidated", status="verified", details={"old_input_sha256": input_sha,
                                      "new_input_sha256": candidate.snapshot_ref, "outcomes": old_results})
                                handled.clear()
                                errors.clear()
                                auxiliary_errors.clear()
                                attempts.clear()
                                # The ledger keeps history. Planning feedback must not present
                                # obsolete qualification failures as valid for the new input.
                                feedback.clear()
                            state = candidate
                        elif tool == "predict_event_24h":
                            value = self.medical.predict(state, deadline, rid, metrics)
                            handled[outcome] = value
                            errors.pop(outcome, None)
                        else:
                            value = self.medical.retrieve(state, deadline, rid, metrics)
                            handled[outcome] = value
                            errors.pop(outcome, None)
                        seen.add((tool, input_sha))
                        auxiliary_errors.pop(tool, None)
                        event("tool_result", tool=tool, status=value["status"], details=value)
                        feedback.append(compact_feedback(tool, value))
                    except Exception as exc:
                        classification = failure(exc)
                        value = {"status": "failed", "reason": classification["type"], "error": classification,
                                 "input_sha256": input_sha}
                        event("tool_result", tool=tool, status="failed", details=value)
                        feedback.append(compact_feedback(tool, value))
                        key = (tool, input_sha)
                        attempts[key] = attempts.get(key, 0) + 1
                        if outcome:
                            # A real failure is already a reportable outcome. The model may
                            # elect a bounded retry, but the harness does not force its route.
                            errors[outcome] = value
                        else:
                            auxiliary_errors[tool] = value
                            # Subsequent actions may rely on the attempted source/state read.
                            # Medical capabilities remain independent after a role-local failure.
                            plan_queue.clear("auxiliary_tool_failed")
                        if not classification["retryable"] or attempts[key] >= 2:
                            seen.add(key)
                            if not outcome:
                                stop = "failed_tool"
                                break
        except RunBudget:
            stop = "budget"
        except Exception as exc:
            event("execution_error", status="failed", details={"error": failure(exc)})
            limits.append("协调执行未返回可接纳结果，保留已完成工具证据。")
            stop = "failed_tool"

        plan_queue.clear("run_terminated:" + stop)
        if stop == "budget":
            limits.append("本次达到执行预算，未完成部分保持未完成状态。")
        limits.extend(tool + ": 资料工具失败，未将失败解释为资料不存在或医学阴性。" for tool in auxiliary_errors)
        result = build_report(state, intent["outcomes"], handled, errors, limits)
        if result["narrative"] and remaining() > 1 and metrics["coordinator_calls"] < self.budget.coordinator:
            try:
                rendered = coordinate("summary", lambda timeout: self.coordinator.summarize(copy.deepcopy(result["narrative"]), timeout=timeout))
                if sorted(rendered, key=lambda r: r["id"]) != sorted(result["narrative"], key=lambda r: r["id"]):
                    raise ContractError("coordinator_modified_verified_statements")
                result["narrative"] = rendered
            except Exception:
                result["limitations"].append("协调器汇总未通过，展示确定性核验陈述。")
        verify_references(result["narrative"], result["evidence"])
        complete_count = sum(value["status"] == "complete" for value in handled.values())
        status = ("needs_clarification" if stop == "clarification" else "succeeded" if stop == "completed" else
                  "partial" if complete_count else "blocked" if stop == "blocked_inputs" else "failed")
        metrics["elapsed_seconds"] = round(time.monotonic() - started, 4)
        result.update(goal_interpretation={**intent, "source": "coordinator"},
                      termination={"code": stop, "origin": termination_origin or (
                          "coordinator_clarification" if stop == "clarification" else "runtime_boundary"),
                          "clarification": clarification, "accounted_outcomes": sorted(set(handled) | set(errors))},
                      metrics=metrics, versions={"api": "competition-v2", "agent": self.version, "state": VERSION,
                                               "source_sha256": self.repository.identity, "reference_index_sha256": self.index.identity},
                      coordinator_mode=self.coordinator.mode, comparison_mode=request["mode"])
        require_no_model_scores(result)
        event("termination", status=status, details=result["termination"])
        self.ledger.finish(rid, status, result)
        return result
