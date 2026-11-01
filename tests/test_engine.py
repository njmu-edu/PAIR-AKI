import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from pair_aki.backend.domain import ContractError
from pair_aki.backend.synthetic import make_case
from pair_aki.specialists.providers import SyntheticPredictor, SyntheticComparator
from pair_aki.autonomous.coordinator import ScriptedCoordinator
from pair_aki.autonomous.engine import Engine
from pair_aki.autonomous.ledger import Ledger
from pair_aki.autonomous.recall import ReferenceIndex
from pair_aki.autonomous.repository import SyntheticRepository
from pair_aki.autonomous.state import Budget, factual_view, admit, require_no_model_scores

P, R = "predict_event_24h", "retrieve_comparable_cases"


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = SyntheticRepository()
        self.index = ReferenceIndex(self.repo.references)
        self.ledger = Ledger(self.tmp.name)

    def execute(self, outcomes, actions, case="ae-201", mode="autonomous", budget=Budget(), predictor=None, coordinator=None):
        coordinator = coordinator or ScriptedCoordinator(outcomes, actions)
        engine = Engine(self.repo, self.index, predictor or SyntheticPredictor(self.repo.labels),
                        SyntheticComparator(), self.ledger, coordinator, budget)
        request = {"goal": "请根据本次目标完成病例评估", "case_ref": case,
                   "snapshot_ref": self.repo.get(case).snapshot_ref, "mode": mode}
        rid = self.ledger.create(request)
        result = engine.execute(rid, request)
        return self.ledger.read(rid), result, coordinator

    def test_binary_success_and_no_probability(self):
        for case, label in (("ae-201", 1), ("ae-202", 0)):
            record, result, coord = self.execute(["event_prediction"], [P, "finish"], case)
            self.assertEqual(record["status"], "succeeded")
            self.assertIs(type(result["prediction"]["label"]), int)
            self.assertEqual(result["prediction"]["label"], label)
            self.assertEqual(result["metrics"]["predictor_forwards"], 1)
            self.assertIsNone(result["comparables"])
            require_no_model_scores(record)
            for view in coord.views:
                self.assertNotIn("required_tools", json.dumps(view))
                self.assertNotIn("expected_label", json.dumps(view))

    def test_blocked_inputs_never_attempt_model(self):
        for case in ("ae-205", "ae-207"):
            record, result, _ = self.execute(["event_prediction", "comparable_cases"], [P, R, "finish"], case)
            self.assertEqual(record["status"], "blocked")
            self.assertEqual(result["termination"]["code"], "blocked_inputs")
            self.assertEqual(result["metrics"]["medical_attempts"], 0)
            self.assertIsNone(result["prediction"])

    def test_repair_invalidates_prior_block_and_uses_new_hash(self):
        record, result, coord = self.execute(["event_prediction"], [P, "get_evidence", P, "finish"], "ae-203")
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(result["metrics"]["predictor_forwards"], 1)
        self.assertEqual(result["prediction"]["receipt"]["input_sha256"], self.repo.expanded["ae-203"].snapshot_ref)
        self.assertTrue(any(e["kind"] == "results_invalidated" for e in record["events"]))
        self.assertFalse(any(f.get("status") == "blocked" for f in coord.views[2]["feedback"]))
        self.assertEqual(coord.views[1]["verified_outcomes"]["event_prediction"]["status"], "blocked")
        self.assertEqual(coord.views[2]["verified_outcomes"], {})
        admissions = coord.views[2]["feedback"][-1]["medical_admission"]
        self.assertIs(admissions["M_P"]["admitted"], True)
        self.assertIs(admissions["M_R"]["admitted"], True)
        self.assertEqual(admissions["M_P"]["input_sha256"], self.repo.expanded["ae-203"].snapshot_ref)

    def test_evidence_mutation_does_not_change_accepted_state(self):
        prior = self.repo.get("ae-203")
        def bad(state):
            state.observations[0]["value"] = 999
            return state
        self.repo.acquire = bad
        record, result, _ = self.execute(["event_prediction"], ["get_evidence"], "ae-203")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(result["final_snapshot"]["snapshot_ref"], prior.snapshot_ref)
        self.assertEqual(result["metrics"]["medical_attempts"], 0)
        self.assertEqual(self.repo.get("ae-203").snapshot_ref, prior.snapshot_ref)

    def test_transient_evidence_failure_can_retry_within_two_repairs(self):
        original = self.repo.acquire
        calls = []
        def transient(state):
            calls.append(state.snapshot_ref)
            if len(calls) == 1:
                raise TimeoutError("bounded source timeout")
            return original(state)
        self.repo.acquire = transient
        record, result, _ = self.execute(["event_prediction"], ["get_evidence", "get_evidence", P, "finish"], "ae-203")
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["metrics"]["repairs"], 2)

    def test_model_population_rejected_before_provider_attempt(self):
        class Narrow(SyntheticPredictor):
            def validate_support(self, snapshot):
                raise ContractError("outside_registered_model_population")
        record, result, _ = self.execute(["event_prediction"], [P, "finish"], predictor=Narrow())
        self.assertEqual(record["status"], "failed")
        self.assertEqual(result["metrics"]["medical_attempts"], 0)

    def test_no_new_evidence_can_end_with_grounded_block(self):
        self.repo.acquire = lambda state: state
        record, result, _ = self.execute(["event_prediction"], [P, "get_evidence", "finish"], "ae-203")
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(result["termination"]["code"], "blocked_inputs")
        self.assertEqual(result["metrics"]["medical_attempts"], 0)

    def test_single_retrieval_two_orders_and_unique_patients(self):
        record, result, coord = self.execute(["comparable_cases"], [R, "finish"])
        self.assertEqual(record["status"], "succeeded")
        self.assertIsNone(result["prediction"])
        matches = result["comparables"]["matches"]
        self.assertEqual(len({m["patient_ref"] for m in matches}), 3)
        self.assertEqual(result["metrics"]["predictor_forwards"], 0)
        n = result["comparables"]["candidate_count"]
        self.assertEqual(result["metrics"]["comparator_forwards"], n * (n - 1))
        self.assertEqual(n, 12)
        require_no_model_scores(record)
        require_no_model_scores(coord.views)
        audits = list((Path(self.tmp.name) / "private-medical-audit").rglob("*.json"))
        self.assertTrue(any("margin" in json.loads(p.read_text())["result"] for p in audits))

    def test_single_task_denies_unrelated_medical_action(self):
        record, result, _ = self.execute(["comparable_cases"], [P, R, "finish"])
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(result["metrics"]["predictor_forwards"], 0)
        self.assertEqual(result["metrics"]["tool_calls"], 1)
        self.assertTrue(any(e.get("status") == "rejected" for e in record["events"]))

    def test_budget_not_correct_refusal(self):
        record, result, _ = self.execute(["event_prediction"], [P], budget=Budget(tools=0))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(result["termination"]["code"], "budget")
        self.assertIsNone(result["prediction"])

    def test_exact_tool_budget_can_finish(self):
        record, result, _ = self.execute(["event_prediction"], [P, "finish"], budget=Budget(tools=1))
        self.assertEqual(record["status"], "succeeded")

    def test_verified_completion_does_not_require_an_extra_planner_call(self):
        record, result, _ = self.execute(["event_prediction"], [P])
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(result["termination"]["origin"], "runtime_postconditions")
        self.assertEqual(result["metrics"]["coordinator_calls"], 3)
        self.assertTrue(any(e["kind"] == "goal_postconditions" for e in record["events"]))

    def test_service_failure_not_binary_zero_or_correct_refusal(self):
        record, result, _ = self.execute(["event_prediction"], [P, P, "finish"], "ae-209")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(result["termination"]["code"], "failed_tool")
        self.assertIsNone(result["prediction"])
        self.assertEqual(result["metrics"]["medical_attempts"], 2)
        self.assertEqual(result["metrics"]["predictor_forwards"], 0)
        self.assertEqual(result["metrics"]["medical_forward_unknown"], 0)

    def test_model_may_end_after_one_real_failure_without_forced_retry(self):
        record, result, _ = self.execute(["event_prediction"], [P, "finish"], "ae-209")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(result["termination"]["code"], "failed_tool")
        self.assertEqual(result["metrics"]["medical_attempts"], 1)
        self.assertEqual(result["metrics"]["repairs"], 0)

    def test_evidence_service_failure_can_end_but_not_as_grounded_refusal(self):
        def unavailable(state):
            raise TimeoutError("source unavailable")
        self.repo.acquire = unavailable
        record, result, _ = self.execute(["event_prediction"], [P, "get_evidence", "finish"], "ae-203")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(result["termination"]["code"], "failed_tool")
        self.assertEqual(result["metrics"]["medical_attempts"], 0)
        self.assertTrue(any("资料工具失败" in reason for reason in result["limitations"]))

    def test_goal_clarification_at_entry_and_no_fake_data_upload_after_gate(self):
        entry = ScriptedCoordinator([], [], clarification="你希望预测事件还是检索病例？")
        record, result, _ = self.execute([], [], coordinator=entry)
        self.assertEqual(record["status"], "needs_clarification")
        self.assertEqual(result["metrics"]["medical_attempts"], 0)
        action = {"tool": "clarify", "reason": "索要缺失资料", "question": "请提供基线", "clarification_kind": "clinical_data"}
        record, result, _ = self.execute(["event_prediction"], [action, P], "ae-205")
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(result["metrics"]["medical_attempts"], 0)
        self.assertTrue(any(e.get("details", {}).get("reason") == "no_clinical_data_upload_channel" for e in record["events"]))

    def test_later_goal_or_permission_clarification_remains_available(self):
        for kind in ("goal", "permission", "case_or_time"):
            action = {"tool": "clarify", "reason": "需要确认任务边界", "question": "请确认本次需要的范围", "clarification_kind": kind}
            record, result, _ = self.execute(["event_prediction"], [action])
            self.assertEqual(record["status"], "needs_clarification")
            self.assertEqual(result["metrics"]["medical_attempts"], 0)

    def test_unnecessary_reconfirmation_uses_budgeted_model_review_not_gold_route(self):
        class Reviewing(ScriptedCoordinator):
            def assess_clarification(self, goal, proposal, *, timeout):
                return {"necessary": False, "reason": "original request already names both capabilities"}, {"mode": self.mode}
        question = {"tool": "clarify", "reason": "确认剩余任务", "question": "是否继续已要求的病例检索？", "clarification_kind": "goal"}
        coord = Reviewing(["event_prediction", "comparable_cases"], [P, question, R, "finish"])
        record, result, _ = self.execute([], [], case="ae-209", coordinator=coord)
        self.assertEqual(result["termination"]["code"], "failed_tool")
        self.assertEqual(result["metrics"]["medical_attempts"], 2)
        self.assertEqual(result["metrics"]["coordinator_calls"], 7)
        self.assertTrue(any(e.get("details", {}).get("reason") == "unnecessary_goal_reconfirmation" for e in record["events"]))

    def test_malformed_coordinator_retained_as_failed(self):
        class Bad(ScriptedCoordinator):
            def interpret(self, goal, *, timeout):
                return {}, {"raw_action": "malformed"}
        record, result, _ = self.execute([], [], coordinator=Bad([], []))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(result["metrics"]["medical_attempts"], 0)
        paths = list((Path(self.tmp.name) / "private-coordinator-audit").rglob("*.json"))
        self.assertTrue(any("malformed" in p.read_text() for p in paths))

    def test_invalid_label_is_not_published(self):
        class Bad(SyntheticPredictor):
            def predict(self, snapshot, *, timeout):
                row = super().predict(snapshot, timeout=timeout)
                row["label"] = False
                return row
        record, result, _ = self.execute(["event_prediction"], [P, "finish"], predictor=Bad(self.repo.labels))
        self.assertEqual(record["status"], "failed")
        self.assertIsNone(result["prediction"])
        self.assertEqual(result["metrics"]["predictor_forwards"], 1)

    def test_nonfinite_response_preserves_failed_medical_receipt(self):
        class Bad(SyntheticPredictor):
            def predict(self, snapshot, *, timeout):
                row = super().predict(snapshot, timeout=timeout)
                row["label"] = float("nan")
                return row
        record, result, _ = self.execute(["event_prediction"], [P, "finish"], predictor=Bad(self.repo.labels))
        calls = [e for e in record["events"] if e["kind"] == "medical_call"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["status"], "failed")
        self.assertIsNone(result["prediction"])
        audits = list((Path(self.tmp.name) / "private-medical-audit").rglob("*.json"))
        self.assertEqual(json.loads(audits[0].read_text())["result"]["label"],
                         {"audit_type": "nonfinite_float", "value": "nan"})

    def test_terminal_record_immutable(self):
        record, _, _ = self.execute(["event_prediction"], [P, "finish"], "ae-205")
        with self.assertRaises(ContractError):
            self.ledger.event(record["run_id"], {"kind": "overwrite"})

    def test_prevalent_case_can_retrieve_but_not_predict(self):
        state = make_case("prevalent", "synthetic", 1460, [30, 31, 32, 33, 62, 64])
        self.assertFalse(admit(state, "M_P", [])["admitted"])
        self.assertTrue(admit(state, "M_R", [])["admitted"])

    def test_recall_excludes_every_timepoint_for_query_patient(self):
        query = self.repo.references[0]
        candidates = self.index.recall(query)
        self.assertNotIn(query.patient_ref, [r["state"].patient_ref for r in candidates])
        self.assertEqual(len(candidates), len({r["state"].patient_ref for r in candidates}))

    def test_inputs_have_no_oracle_fields_and_manifest_is_offline(self):
        public = json.dumps(self.repo.list_cases())
        for field in ("eligibility_reason", "prediction_eligible", "expected_label", "required_tools", "evidence_complete"):
            self.assertNotIn(field, public)
        self.assertEqual(self.repo.evaluation_manifest()["reference_index_sha256"], self.index.identity)

    def test_source_catalog_is_real_metadata_not_values_or_route(self):
        state = self.repo.get("ae-203")
        catalog = self.repo.source_catalog(state)
        self.assertEqual(catalog[0]["records_not_yet_loaded"], 5)
        self.assertEqual(catalog[0]["qualified_record_count"], 6)
        self.assertEqual(catalog[0]["access"], "already_authorized_read_only")
        self.assertEqual(self.repo.source_catalog(self.repo.acquire(state)), [])
        for field in ("expected_label", "next_tool", "required_tools", "value", "route"):
            self.assertNotIn(field, catalog[0])

    def test_fixed_baseline_uses_same_model_goal_interpretation(self):
        record, result, _ = self.execute(["event_prediction"], [], "ae-203", mode="fixed")
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(result["goal_interpretation"]["source"], "coordinator")
        self.assertEqual(result["metrics"]["comparator_forwards"], 0)


if __name__ == "__main__":
    unittest.main()
