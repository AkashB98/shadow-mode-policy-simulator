"""Shadow-mode simulation: replay traces under two policies and diff the verdicts.

For every step of every historical trace we evaluate the *baseline* policy
(what is live today) and the *candidate* policy (the proposed change) and
classify the delta:

- ``unchanged``            — same verdict under both policies
- ``allow_to_approval``    — NEW FRICTION: was instant, now needs a human
- ``allow_to_deny``        — NEW BLOCK: was instant, now refused
- ``approval_to_allow``    — NEW AUTOMATION: approval queue shrinks
- ``approval_to_deny``     — NEW BLOCK: was approvable, now refused
- ``deny_to_allow``        — LOOSENED: was refused, now instant
- ``deny_to_approval``     — LOOSENED: was refused, now approvable

Aggregates roll up per tool and per driving rule, so the report can answer
the operator's real question: *which rule change caused the biggest blast
radius?*
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .policy import Policy, Decision
from .traces import Trace

#: (old_action, new_action) -> delta label
DELTA_LABELS = {
    ("allow", "allow"): "unchanged",
    ("allow", "require_approval"): "allow_to_approval",
    ("allow", "deny"): "allow_to_deny",
    ("require_approval", "allow"): "approval_to_allow",
    ("require_approval", "require_approval"): "unchanged",
    ("require_approval", "deny"): "approval_to_deny",
    ("deny", "allow"): "deny_to_allow",
    ("deny", "require_approval"): "deny_to_approval",
    ("deny", "deny"): "unchanged",
}

#: delta -> severity bucket for CI gates and headlines
DELTA_SEVERITY = {
    "unchanged": "none",
    "allow_to_approval": "friction",
    "allow_to_deny": "block",
    "approval_to_allow": "automation",
    "approval_to_deny": "block",
    "deny_to_allow": "loosened",
    "deny_to_approval": "loosened",
}

CHANGED = ("allow_to_approval", "allow_to_deny", "approval_to_allow",
           "approval_to_deny", "deny_to_allow", "deny_to_approval")


@dataclass
class StepResult:
    trace_id: str
    seq: int
    tool: str
    args: Dict[str, Any]
    old_action: str
    old_rule: str
    new_action: str
    new_rule: str
    delta: str

    @property
    def changed(self) -> bool:
        return self.delta != "unchanged"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "seq": self.seq,
            "tool": self.tool,
            "args": self.args,
            "old_action": self.old_action,
            "old_rule": self.old_rule,
            "new_action": self.new_action,
            "new_rule": self.new_rule,
            "delta": self.delta,
        }


@dataclass
class TraceImpact:
    trace_id: str
    steps: int
    new_denials: int
    new_approvals: int
    new_automations: int
    loosened: int
    changed: int

    @property
    def status(self) -> str:
        """Trace-level verdict: stalls / changed / clean."""
        if self.new_denials:
            return "stalls"      # at least one step is newly refused
        if self.changed:
            return "changed"
        return "clean"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "steps": self.steps,
            "new_denials": self.new_denials,
            "new_approvals": self.new_approvals,
            "new_automations": self.new_automations,
            "loosened": self.loosened,
            "changed": self.changed,
            "status": self.status,
        }


@dataclass
class Simulation:
    baseline_name: str
    candidate_name: str
    steps: List[StepResult] = field(default_factory=list)
    trace_impacts: List[TraceImpact] = field(default_factory=list)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def changed_steps(self) -> List[StepResult]:
        return [s for s in self.steps if s.changed]

    def delta_counts(self) -> Dict[str, int]:
        counts = Counter(s.delta for s in self.steps)
        return {label: counts.get(label, 0) for label in
                ["unchanged", "allow_to_approval", "allow_to_deny",
                 "approval_to_allow", "approval_to_deny",
                 "deny_to_allow", "deny_to_approval"]}

    def per_tool(self) -> Dict[str, Dict[str, int]]:
        """tool -> {delta: count} rollup."""
        agg: Dict[str, Counter] = {}
        for s in self.steps:
            agg.setdefault(s.tool, Counter())[s.delta] += 1
        return {tool: dict(c) for tool, c in sorted(agg.items())}

    def driving_rules(self) -> List[Dict[str, Any]]:
        """Candidate rules ranked by how many step verdicts they changed.

        The ops insight: the rule with the biggest blast radius is the one
        to review, split, or roll back — not the policy as a whole.
        """
        counter: Counter = Counter()
        examples: Dict[str, StepResult] = {}
        for s in self.changed_steps:
            counter[s.new_rule] += 1
            if s.new_rule not in examples:
                examples[s.new_rule] = s
        out = []
        for rule, n in counter.most_common():
            out.append({
                "rule": rule,
                "changed_steps": n,
                "example": {
                    "tool": examples[rule].tool,
                    "delta": examples[rule].delta,
                },
            })
        return out

    def summary(self) -> Dict[str, Any]:
        counts = self.delta_counts()
        total = self.total_steps
        stalls = sum(1 for t in self.trace_impacts if t.status == "stalls")
        return {
            "baseline": self.baseline_name,
            "candidate": self.candidate_name,
            "traces": len(self.trace_impacts),
            "steps": total,
            "delta_counts": counts,
            "new_approvals": counts["allow_to_approval"],
            "new_denials": counts["allow_to_deny"] + counts["approval_to_deny"],
            "new_automations": counts["approval_to_allow"],
            "loosened": counts["deny_to_allow"] + counts["deny_to_approval"],
            "new_denial_rate": _rate(counts["allow_to_deny"] + counts["approval_to_deny"], total),
            "new_approval_rate": _rate(counts["allow_to_approval"], total),
            "changed_rate": _rate(total - counts["unchanged"], total),
            "traces_stalled": stalls,
            "traces_changed": sum(1 for t in self.trace_impacts if t.status == "changed"),
            "traces_clean": sum(1 for t in self.trace_impacts if t.status == "clean"),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary(),
            "per_tool": self.per_tool(),
            "driving_rules": self.driving_rules(),
            "traces": [t.to_dict() for t in self.trace_impacts],
            "changed_steps": [s.to_dict() for s in self.changed_steps],
        }


def _rate(n: int, total: int) -> float:
    return round(n / total, 4) if total else 0.0


def classify(old: Decision, new: Decision) -> str:
    return DELTA_LABELS[(old.action, new.action)]


def run(baseline: Policy, candidate: Policy,
        traces: List[Trace]) -> Simulation:
    """Replay every trace under both policies and diff the verdicts."""
    sim = Simulation(baseline_name=baseline.name, candidate_name=candidate.name)
    for trace in traces:
        new_denials = new_approvals = new_automations = loosened = changed = 0
        for step in trace.steps:
            old = baseline.evaluate(step.tool, step.args)
            new = candidate.evaluate(step.tool, step.args)
            delta = classify(old, new)
            sim.steps.append(StepResult(
                trace_id=trace.trace_id,
                seq=step.seq,
                tool=step.tool,
                args=step.args,
                old_action=old.action,
                old_rule=old.rule_name,
                new_action=new.action,
                new_rule=new.rule_name,
                delta=delta,
            ))
            if delta == "unchanged":
                continue
            changed += 1
            if delta in ("allow_to_deny", "approval_to_deny"):
                new_denials += 1
            elif delta == "allow_to_approval":
                new_approvals += 1
            elif delta == "approval_to_allow":
                new_automations += 1
            else:  # deny_to_allow, deny_to_approval
                loosened += 1
        sim.trace_impacts.append(TraceImpact(
            trace_id=trace.trace_id,
            steps=len(trace.steps),
            new_denials=new_denials,
            new_approvals=new_approvals,
            new_automations=new_automations,
            loosened=loosened,
            changed=changed,
        ))
    return sim
