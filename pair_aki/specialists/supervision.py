"""Train-only three-group weak supervision; no outcome labels are accepted."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from collections import defaultdict, deque
from datetime import datetime
from pair_aki.backend.domain import Snapshot, ContractError, FEATURE_GROUPS, digest
from .contracts import comparison_eligibility, validate_pair

RULE_VERSION = "three-groups-train-range-pair-v1"
PREFERENCE_GAP = 0.05


@dataclass(frozen=True)
class PairExample:
    query: Snapshot
    left: Snapshot
    right: Snapshot
    label: int  # index of native A/B candidate: 0=A, 1=B
    rule_margin: float
    rule_sha256: str


class ThreeGroupRule:
    def __init__(self, train_states: list[Snapshot]):
        if not train_states or any(s.split != "train" for s in train_states):
            raise ContractError("weak_rule_fit_train_only")
        if len({s.snapshot_ref for s in train_states}) != len(train_states):
            raise ContractError("weak_rule_duplicate_state")
        if any(not comparison_eligibility(s)[0] for s in train_states):
            raise ContractError("weak_rule_unqualified_state")
        self.reference_hashes = frozenset(s.snapshot_ref for s in train_states)
        self.ranges = {}
        for names in FEATURE_GROUPS.values():
            for name in names:
                values = [s.features()[name] for s in train_states if s.features()[name] is not None]
                self.ranges[name] = (min(values), max(values)) if values else None
        self.identity = digest({"version": RULE_VERSION, "groups": FEATURE_GROUPS, "ranges": self.ranges,
                                "fit_states": sorted(s.snapshot_ref for s in train_states), "outcomes_used": False})

    def score(self, query: Snapshot, candidate: Snapshot) -> float:
        if query.patient_ref == candidate.patient_ref:
            raise ContractError("weak_rule_self_patient")
        if not all(comparison_eligibility(s)[0] for s in (query, candidate)):
            raise ContractError("weak_rule_unqualified_state")
        q, c = query.features(), candidate.features()
        groups = []
        for names in FEATURE_GROUPS.values():
            values = []
            for name in names:
                bounds, a, b = self.ranges[name], q[name], c[name]
                if bounds is None or a is None or b is None:
                    values.append(0.)
                else:
                    span = bounds[1] - bounds[0]
                    distance = min(abs(a - b) / span, 1.) if span > 0 else float(a != b)
                    values.append(1. - distance)
            groups.append(sum(values) / len(names))
        return sum(groups) / len(groups)

    def pair(self, query: Snapshot, left: Snapshot, right: Snapshot) -> PairExample | None:
        validate_pair(query, left, right)
        margin = self.score(query, left) - self.score(query, right)
        if abs(margin) + 1e-12 < PREFERENCE_GAP:
            return None
        return PairExample(query, left, right, int(margin < 0), margin, self.identity)


@dataclass(frozen=True)
class PairBuild:
    examples: tuple[PairExample, ...]
    statistics: dict


def build_pairs_with_report(queries: list[Snapshot], rule: ThreeGroupRule, *, reference_states=None,
                            max_pairs: int = 10000, candidate_limit: int = 12,
                            reference_time_policy="per_state_only") -> PairBuild:
    """Train reference retrieval, patient-balanced query budget and bounded pairs.

    Dev queries compare against the same frozen Train library as deployment.
    Each query recalls at most 12 distinct patients (best timepoint per patient),
    reducing candidate enumeration from cubic to Nquery*Nref + Nquery*66.
    """
    if type(max_pairs) is not int or max_pairs < 1:
        raise ContractError("weak_pair_budget")
    if type(candidate_limit) is not int or not 2 <= candidate_limit <= 12:
        raise ContractError("weak_pair_candidate_limit")
    if reference_time_policy not in {"per_state_only", "shared_calendar_historical"}:
        raise ContractError("weak_pair_reference_clock_policy")
    if not queries or len({s.split for s in queries}) != 1 or queries[0].split not in {"train", "dev"}:
        raise ContractError("weak_pairs_single_train_or_dev_split")
    references = queries if reference_states is None else reference_states
    if not references or any(s.split != "train" for s in references):
        raise ContractError("weak_pairs_frozen_train_references_required")
    if len(references) != len(rule.reference_hashes) or {s.snapshot_ref for s in references} != rule.reference_hashes:
        raise ContractError("weak_pairs_reference_library_changed")
    queues = defaultdict(list)
    candidate_counts, dropped_small_gap, evaluated = {}, 0, 0
    def when(state):
        return datetime.fromisoformat(state.decision_time.replace("Z", "+00:00"))
    for query in sorted(queries, key=lambda s: s.snapshot_ref):
        best = {}
        for candidate in references:
            if (candidate.patient_ref == query.patient_ref
                    or (reference_time_policy == "shared_calendar_historical" and when(candidate) > when(query))):
                continue
            scored = (rule.score(query, candidate), candidate)
            prior = best.get(candidate.patient_ref)
            if prior is None or (-scored[0], candidate.snapshot_ref) < (-prior[0], prior[1].snapshot_ref):
                best[candidate.patient_ref] = scored
        candidates = [row[1] for row in sorted(best.values(), key=lambda row: (-row[0], row[1].snapshot_ref))[:candidate_limit]]
        candidate_counts[query.snapshot_ref] = len(candidates)
        query_pairs = []
        for left, right in combinations(candidates, 2):
            evaluated += 1
            pair = rule.pair(query, left, right)
            if pair is not None:
                query_pairs.append(pair)
            else:
                dropped_small_gap += 1
        if query_pairs:
            queues[query.patient_ref].append(deque(query_pairs))
    # Round-robin both patients and their query timepoints; a patient with many
    # snapshots does not consume the budget before other patients are visited.
    queues = {patient: deque(items) for patient, items in sorted(queues.items())}
    result = []
    while queues and len(result) < max_pairs:
        for patient in list(queues):
            timepoints = queues[patient]
            current = timepoints.popleft()
            result.append(current.popleft())
            if current:
                timepoints.append(current)
            if not timepoints:
                del queues[patient]
            if len(result) == max_pairs:
                break
    selected_per_patient = defaultdict(int)
    for pair in result:
        selected_per_patient[pair.query.patient_ref] += 1
    statistics = {"queries": len(queries), "query_patients": len({s.patient_ref for s in queries}),
                  "reference_states": len(references), "candidate_limit": candidate_limit,
                  "pairs_evaluated": evaluated, "below_gap": dropped_small_gap, "pairs_selected": len(result),
                  "selected_query_patients": len(selected_per_patient), "selected_per_patient": dict(selected_per_patient),
                  "queries_with_fewer_than_two_candidates": sum(n < 2 for n in candidate_counts.values()),
                  "budget_exhausted": bool(queues), "rule_sha256": rule.identity,
                  "reference_time_policy": reference_time_policy,
                  "reference_sha256": digest(sorted(s.snapshot_ref for s in references))}
    return PairBuild(tuple(result), statistics)


def build_pairs(queries, rule, *, reference_states=None, max_pairs=10000):
    return list(build_pairs_with_report(queries, rule, reference_states=reference_states, max_pairs=max_pairs).examples)
