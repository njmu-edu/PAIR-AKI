from dataclasses import replace
import unittest

from pair_aki.autonomous.coordinator import ScriptedCoordinator
from pair_aki.autonomous.plans import BINDING, PlanQueue, validate_plan
from pair_aki.autonomous.state import Budget
from pair_aki.backend.domain import ContractError
from tests import test_engine

P, R = "predict_event_24h", "retrieve_comparable_cases"
BOTH = ["event_prediction", "comparable_cases"]


def plan(*actions):
    return {"reason": "explicit model-plan fixture", "state_binding": BINDING,
            "actions": list(actions), "question": None, "clarification_kind": None}


class PlanTests(unittest.TestCase):
    setUp = test_engine.EngineTests.setUp
    execute = test_engine.EngineTests.execute

    def test_plan_schema_finish_only_once_and_last(self):
        for actions in (("finish", P), ("finish", P, "finish"), ("clarify", P)):
            with self.assertRaises(ContractError):
                validate_plan(plan(*actions))
        self.assertEqual([x["tool"] for x in validate_plan(plan(P, "finish"))], [P, "finish"])

    def test_model_can_include_explicit_disposition_after_three_tools(self):
        record, result, _ = self.execute(BOTH, [plan("get_evidence", P, R, "finish")], "ae-209")
        self.assertEqual(result["termination"]["code"], "failed_tool")
        self.assertEqual(result["termination"]["origin"], "coordinator_finish")
        self.assertEqual(result["metrics"]["medical_attempts"], 2)
        self.assertEqual(result["metrics"]["coordinator_calls"], 3)
        self.assertEqual(result["metrics"]["tool_calls"], 3)

    def test_early_plan_finish_cannot_hide_an_unhandled_goal(self):
        record, result, _ = self.execute(BOTH, [plan(P, "finish"), plan(R, "finish")], "ae-209")
        self.assertEqual(result["termination"]["code"], "failed_tool")
        self.assertEqual(result["metrics"]["medical_attempts"], 2)
        self.assertEqual(result["metrics"]["repairs"], 1)
        self.assertTrue(any(e.get("details", {}).get("reason") == "missing_verified_task_evidence" for e in record["events"]))

    def test_atomic_evidence_rebinds_remaining_actions_and_records_both_hashes(self):
        record, result, _ = self.execute(BOTH, [plan("get_evidence", P, R)], "ae-203")
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(result["metrics"]["tool_calls"], 3)
        self.assertEqual(result["metrics"]["coordinator_calls"], 3)
        selected = [e["details"] for e in record["events"] if e["kind"] == "planned_action"]
        self.assertEqual([x["action_index"] for x in selected], [1, 2, 3])
        self.assertNotEqual(selected[0]["execution_input_sha256"], selected[1]["execution_input_sha256"])
        self.assertEqual(selected[0]["proposal_input_sha256"], selected[1]["proposal_input_sha256"])
        self.assertEqual(selected[1]["execution_input_sha256"], selected[2]["execution_input_sha256"])
        self.assertEqual(result["metrics"]["predictor_forwards"], 1)
        self.assertEqual(result["metrics"]["comparator_forwards"], 132)

    def test_whole_plan_permissions_checked_before_valid_prefix(self):
        record, result, _ = self.execute(["event_prediction"], [plan(P, R), plan(P)])
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(result["metrics"]["tool_calls"], 1)
        self.assertEqual(result["metrics"]["comparator_forwards"], 0)
        proposals = [e for e in record["events"] if e["kind"] == "short_plan"]
        self.assertEqual([e["status"] for e in proposals], ["rejected", "accepted"])
        selected = [e["details"]["plan_ref"] for e in record["events"] if e["kind"] == "planned_action"]
        self.assertEqual(selected, ["plan-2"])

    def test_role_failure_does_not_cancel_other_independent_capability(self):
        record, result, _ = self.execute(BOTH, [plan(P, R, "finish")], "ae-209")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(result["termination"]["code"], "failed_tool")
        self.assertEqual(result["metrics"]["medical_attempts"], 2)
        self.assertEqual(result["metrics"]["coordinator_calls"], 3)
        self.assertEqual(result["metrics"]["repairs"], 0)
        self.assertEqual(result["termination"]["accounted_outcomes"], sorted(BOTH))

    def test_source_failure_discards_plan_without_inventing_missing_data(self):
        def unavailable(state):
            raise TimeoutError("synthetic source unavailable")
        self.repo.acquire = unavailable
        record, result, coord = self.execute(BOTH, [plan("get_evidence", P, R), plan("finish")], "ae-203")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(result["metrics"]["tool_calls"], 1)
        self.assertEqual(result["metrics"]["medical_attempts"], 0)
        discarded = [e["details"] for e in record["events"] if e["kind"] == "short_plan_remainder"]
        self.assertEqual(discarded[0]["reason"], "auxiliary_tool_failed")
        self.assertEqual([a["tool"] for a in discarded[0]["actions"]], [P, R])
        self.assertIn("get_evidence", coord.views[-1]["auxiliary_failures"])

    def test_budget_applies_between_queued_actions(self):
        record, result, _ = self.execute(BOTH, [plan(P, R)], budget=Budget(tools=1))
        self.assertEqual(record["status"], "partial")
        self.assertEqual(result["termination"]["code"], "budget")
        self.assertEqual(result["metrics"]["predictor_forwards"], 1)
        self.assertEqual(result["metrics"]["comparator_forwards"], 0)

    def test_verified_completion_discards_unexecuted_tail(self):
        record, result, _ = self.execute(["event_prediction"], [plan(P, "read_case_state")])
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(result["metrics"]["tool_calls"], 1)
        discarded = [e["details"] for e in record["events"] if e["kind"] == "short_plan_remainder"]
        self.assertEqual(discarded[0]["reason"], "run_terminated:completed")

    def test_rejected_step_discards_tail_and_replans_from_actual_feedback(self):
        record, result, coord = self.execute(BOTH, [plan(P, P, R), plan(R)])
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(result["metrics"]["tool_calls"], 2)
        self.assertEqual(result["metrics"]["repairs"], 1)
        self.assertEqual(coord.views[-1]["feedback"][-1]["reason"], "same_input_already_handled")

    def test_queue_rejects_case_or_time_substitution(self):
        queue = PlanQueue(lambda *a, **kw: None)
        original = self.repo.get("ae-201")
        queue.load(plan(P), original, ["event_prediction"])
        for field in ("case_ref", "patient_ref", "episode_ref", "decision_time"):
            changed = replace(original, **{field: getattr(original, field) + "changed"})
            with self.assertRaises(ContractError):
                queue.pop(changed)
        self.assertEqual(queue.pop(original)["tool"], P)


if __name__ == "__main__":
    unittest.main()
