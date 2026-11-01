"""Model-authored short plans; no business route is supplied by this module."""
from pair_aki.backend.domain import ContractError
from .state import TOOLS, OUTCOME_TOOL

BINDING = "latest_accepted_same_case_and_time"
PLAN_SCHEMA = {"anyOf": [
    {"type": "object", "properties": {
        "reason": {"type": "string", "minLength": 1, "maxLength": 240},
        "state_binding": {"const": BINDING},
        "actions": {"type": "array", "items": {"type": "string", "enum": [*TOOLS, "finish"]}, "minItems": 1, "maxItems": 4},
        "question": {"type": "null"}, "clarification_kind": {"type": "null"}},
     "required": ["reason", "state_binding", "actions", "question", "clarification_kind"], "additionalProperties": False},
    {"type": "object", "properties": {
        "reason": {"type": "string", "minLength": 1, "maxLength": 240},
        "state_binding": {"const": BINDING},
        "actions": {"type": "array", "items": {"const": "clarify"}, "minItems": 1, "maxItems": 1},
        "question": {"type": "string", "minLength": 1},
        "clarification_kind": {"type": "string", "enum": ["goal", "permission", "case_or_time", "clinical_data"]}},
     "required": ["reason", "state_binding", "actions", "question", "clarification_kind"], "additionalProperties": False},
]}


def validate_plan(plan):
    if (not isinstance(plan, dict) or set(plan) != {"reason", "state_binding", "actions", "question", "clarification_kind"}
            or plan["state_binding"] != BINDING or not isinstance(plan["reason"], str)
            or not 1 <= len(plan["reason"].strip()) <= 240 or not isinstance(plan["actions"], list)
            or not 1 <= len(plan["actions"]) <= 4
            or any(type(x) is not str or x not in {*TOOLS, "finish", "clarify"} for x in plan["actions"])):
        raise ContractError("short_plan_schema")
    if "clarify" in plan["actions"]:
        if (plan["actions"] != ["clarify"] or plan["clarification_kind"] not in {"goal", "permission", "case_or_time", "clinical_data"}
                or not isinstance(plan["question"], str) or not plan["question"].strip()):
            raise ContractError("clarification_plan_must_stand_alone")
    elif plan["question"] is not None or plan["clarification_kind"] is not None:
        raise ContractError("tool_plan_cannot_ask_question")
    if "finish" in plan["actions"][:-1]:
        raise ContractError("finish_must_be_last")
    return [{"tool": tool, "reason": plan["reason"], "question": plan["question"],
             "clarification_kind": plan["clarification_kind"]} for tool in plan["actions"]]


def out_of_scope(actions, outcomes):
    reverse = {tool: name for name, tool in OUTCOME_TOOL.items()}
    return [action["tool"] for action in actions if action["tool"] in reverse and reverse[action["tool"]] not in outcomes]


class PlanQueue:
    """Execute only the model's unconditional choices, with explicit snapshot binding."""

    def __init__(self, event):
        self.event = event
        self.pending = []
        self.sequence = 0

    @staticmethod
    def scope(state):
        return (state.case_ref, state.patient_ref, state.episode_ref, state.decision_time)

    def load(self, plan, state, outcomes):
        actions = validate_plan(plan)
        self.sequence += 1
        self.plan_ref = "plan-" + str(self.sequence)
        denied = out_of_scope(actions, outcomes)
        self.event("short_plan", status="rejected" if denied else "accepted", details={
            "plan_ref": self.plan_ref, "input_sha256": state.snapshot_ref, "proposal": plan,
            "outside_goal": denied})
        if denied:
            # Reject the whole proposal before executing even its valid prefix.
            # The normal permission gate supplies the actual correction feedback.
            return next(action for action in actions if action["tool"] in denied)
        self.bound_scope = self.scope(state)
        self.proposed_sha = state.snapshot_ref
        self.pending = list(enumerate(actions, start=1))
        return None

    def pop(self, state):
        if self.scope(state) != self.bound_scope:
            raise ContractError("short_plan_case_or_time_changed")
        index, action = self.pending.pop(0)
        self.event("planned_action", status="selected", details={"plan_ref": self.plan_ref,
            "action_index": index, "proposal_input_sha256": self.proposed_sha,
            "execution_input_sha256": state.snapshot_ref, "state_binding": BINDING, **action})
        return action

    def clear(self, reason):
        if self.pending:
            self.event("short_plan_remainder", status="discarded", details={
                "plan_ref": self.plan_ref, "reason": reason,
                "actions": [{"action_index": index, "tool": action["tool"]} for index, action in self.pending]})
        self.pending = []
