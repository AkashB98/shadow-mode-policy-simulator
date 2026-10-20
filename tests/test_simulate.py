"""Simulation (dual-eval + delta classification + rollups) unit tests."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_policy import (
    Policy, Decision, Trace, Step, run, classify, DELTA_LABELS,
)
from shadow_policy.demo_scenario import (
    BASELINE_POLICY, CANDIDATE_POLICY, build_traces, write_fixtures,
)
from shadow_policy.policy import Policy as _P  # noqa: F401 (re-export sanity)


def _pol(name, rules, default="require_approval"):
    return Policy(name=name, default_action=default, rules=rules)


class TestDeltaMatrix(unittest.TestCase):
    """All 9 (old, new) pairs classify to the documented label."""

    def test_all_pairs(self):
        for (old, new), label in DELTA_LABELS.items():
            self.assertEqual(classify(Decision(old, "r"), Decision(new, "r")),
                             label, f"{old}->{new}")

    def test_all_nine_pairs_covered(self):
        self.assertEqual(len(DELTA_LABELS), 9)


class TestRun(unittest.TestCase):
    def setUp(self):
        self.old = _pol("v1", [
            {"name": "allow reads", "tool": "read.*", "action": "allow"},
        ])
        self.new = _pol("v2", [
            {"name": "allow reads", "tool": "read.*", "action": "allow"},
            {"name": "tighten writes", "tool": "write.*", "action": "require_approval"},
            {"name": "ban drops", "tool": "db.drop", "action": "deny"},
        ])

    def _trace(self, tid, calls):
        return Trace(trace_id=tid,
                     steps=[Step(seq=i, tool=t, args=a)
                            for i, (t, a) in enumerate(calls)])

    def test_deltas(self):
        # v1: write.* -> default require_approval, db.drop -> default require_approval
        sim = run(self.old, self.new, [
            self._trace("a", [("read.x", {}), ("write.y", {}), ("db.drop", {})]),
        ])
        deltas = [s.delta for s in sim.steps]
        self.assertEqual(deltas, ["unchanged", "unchanged", "approval_to_deny"])
        s = sim.summary()
        self.assertEqual(s["new_denials"], 1)
        self.assertEqual(s["new_approvals"], 0)
        self.assertEqual(s["traces_stalled"], 1)
        self.assertEqual(sim.trace_impacts[0].status, "stalls")

    def test_allow_to_approval_and_back(self):
        old = _pol("v1", [{"name": "auto", "tool": "pay.refund",
                           "args": {"amount": {"lte": 500}}, "action": "allow"}])
        new = _pol("v2", [{"name": "auto", "tool": "pay.refund",
                           "args": {"amount": {"lte": 100}}, "action": "allow"}])
        sim = run(old, new, [
            self._trace("a", [("pay.refund", {"amount": 50}),
                              ("pay.refund", {"amount": 300})]),
        ])
        self.assertEqual([s.delta for s in sim.steps],
                         ["unchanged", "allow_to_approval"])
        self.assertEqual(sim.summary()["new_approvals"], 1)
        self.assertEqual(sim.trace_impacts[0].status, "changed")

    def test_rule_attribution(self):
        sim = run(self.old, self.new, [
            self._trace("a", [("db.drop", {}), ("db.drop", {"x": 1}),
                              ("read.x", {})]),
        ])
        driving = sim.driving_rules()
        self.assertEqual(driving[0]["rule"], "ban drops")
        self.assertEqual(driving[0]["changed_steps"], 2)
        self.assertEqual(driving[0]["example"]["delta"], "approval_to_deny")

    def test_per_tool_rollup(self):
        sim = run(self.old, self.new, [
            self._trace("a", [("db.drop", {}), ("db.drop", {})]),
        ])
        per = sim.per_tool()
        self.assertEqual(per["db.drop"]["approval_to_deny"], 2)

    def test_clean_trace(self):
        sim = run(self.old, self.new, [self._trace("a", [("read.x", {})])])
        self.assertEqual(sim.trace_impacts[0].status, "clean")
        self.assertEqual(sim.summary()["changed_rate"], 0.0)


class TestFixtureScenario(unittest.TestCase):
    """The demo fixture scenario must produce its documented headline."""

    def test_headline_numbers(self):
        from shadow_policy.demo_scenario import run as run_demo
        sim, _ctx = run_demo()
        s = sim.summary()
        self.assertEqual(s["steps"], 30)
        self.assertEqual(s["traces"], 5)
        self.assertEqual(s["new_approvals"], 7)
        self.assertEqual(s["new_denials"], 2)
        self.assertEqual(s["new_automations"], 0)
        self.assertEqual(s["traces_stalled"], 1)
        self.assertEqual(s["traces_changed"], 3)
        self.assertEqual(s["traces_clean"], 1)
        top = sim.driving_rules()[0]
        self.assertEqual(top["rule"], "refunds over $200 need approval")
        self.assertEqual(top["changed_steps"], 4)

    def test_stalled_trace_is_t002(self):
        from shadow_policy.demo_scenario import run as run_demo
        sim, _ctx = run_demo()
        stalled = [t for t in sim.trace_impacts if t.status == "stalls"]
        self.assertEqual([t.trace_id for t in stalled], ["t-002"])
        self.assertEqual(stalled[0].new_denials, 2)

    def test_fixtures_roundtrip(self):
        import tempfile
        from shadow_policy import load_policy, load_traces
        from shadow_policy.demo_scenario import run as run_demo
        with tempfile.TemporaryDirectory() as d:
            paths = write_fixtures(d)
            self.assertIn("baseline_policy.json", paths)
            base = load_policy(os.path.join(d, "baseline_policy.json"))
            cand = load_policy(os.path.join(d, "candidate_policy.json"))
            traces = load_traces(os.path.join(d, "traces"))
            self.assertEqual(len(traces), 5)
            sim = run(base, cand, traces)
            mem_sim, _ = run_demo()
            self.assertEqual(sim.summary(), mem_sim.summary())


if __name__ == "__main__":
    unittest.main()
