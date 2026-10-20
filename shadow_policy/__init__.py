"""shadow-mode-policy-simulator: dry-run approval-policy changes against history."""

from .policy import Policy, Decision, load_policy, rule_matches, VALID_ACTIONS
from .traces import Trace, Step, load_traces, load_trace_file
from .simulate import (Simulation, StepResult, TraceImpact, run, classify,
                       DELTA_LABELS, DELTA_SEVERITY, CHANGED)
from .report import render

__all__ = [
    "Policy", "Decision", "load_policy", "rule_matches", "VALID_ACTIONS",
    "Trace", "Step", "load_traces", "load_trace_file",
    "Simulation", "StepResult", "TraceImpact", "run", "classify",
    "DELTA_LABELS", "DELTA_SEVERITY", "CHANGED",
    "render",
]
