import unittest
from pair_aki.autonomous.completion import terminal_postconditions


class CompletionTests(unittest.TestCase):
    def test_unhandled_or_old_snapshot_never_auto_finishes(self):
        self.assertIsNone(terminal_postconditions(["event_prediction"], {}, {}, {}, "a", [], set(), {}))
        handled = {"event_prediction": {"status": "complete", "admission": {"input_sha256": "old"}}}
        self.assertIsNone(terminal_postconditions(["event_prediction"], handled, {}, {}, "new", [], set(), {}))

    def test_pending_source_not_exhausted_and_auxiliary_failure_not_success(self):
        handled = {"event_prediction": {"status": "blocked", "admission": {"input_sha256": "a"}}}
        self.assertIsNone(terminal_postconditions(["event_prediction"], handled, {}, {}, "a", ["history"], set(), {}))
        done = terminal_postconditions(["event_prediction"], handled, {}, {}, "a", ["history"], {("get_evidence", "a")}, {})
        self.assertEqual(done["code"], "blocked_inputs")
        self.assertIsNone(terminal_postconditions(["event_prediction"], handled, {}, {"get_evidence": {}}, "a", [], set(), {}))

    def test_first_retryable_failure_remains_a_model_choice(self):
        errors = {"event_prediction": {"status": "failed", "input_sha256": "a", "error": {"retryable": True}}}
        self.assertIsNone(terminal_postconditions(["event_prediction"], {}, errors, {}, "a", [], set(), {("predict_event_24h", "a"): 1}))
        done = terminal_postconditions(["event_prediction"], {}, errors, {}, "a", [], set(), {("predict_event_24h", "a"): 2})
        self.assertEqual(done["code"], "failed_tool")
