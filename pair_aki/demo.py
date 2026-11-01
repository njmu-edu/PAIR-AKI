"""Explicit scripted fixture workflow for installation checks; never reported as a live LLM."""
import threading
from pair_aki.autonomous.coordinator import ScriptedCoordinator


class DemoCoordinator:
    mode = 'scripted_test'
    model_id = 'coordinator-scripted-fixture'

    def __init__(self):
        self._local = threading.local()

    def interpret(self, goal, *, timeout):
        text = goal.lower()
        risk = any(word in text for word in ('预测', 'predict', 'risk'))
        similar = any(word in text for word in ('病例', '检索', 'similar', 'comparab', 'retriev'))
        if any(word in text for word in ('联合', 'combined')):
            risk = similar = True
        if any(word in text for word in ('只预测', '不需要找', 'only predict')):
            risk, similar = True, False
        if any(word in text for word in ('只找', '不做事件预测', 'only retriev')):
            risk, similar = False, True
        outcomes = (['event_prediction'] if risk else []) + (['comparable_cases'] if similar else [])
        if not outcomes:
            outcomes = ['event_prediction', 'comparable_cases']
        actions = ['read_case_state', 'get_evidence']
        actions += ['predict_event_24h'] if risk or not similar else []
        actions += ['retrieve_comparable_cases'] if similar or not risk else []
        actions += ['finish']
        self._local.coordinator = ScriptedCoordinator(outcomes, actions)
        return self._local.coordinator.interpret(goal, timeout=timeout)

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._local.coordinator, name)
