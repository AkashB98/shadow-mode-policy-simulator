"""CLI unit tests (simulate/diff/check exit codes and output)."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_policy.demo_scenario import write_fixtures
from shadow_policy.cli import main


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_fixtures(cls.tmp.name)
        cls.base = os.path.join(cls.tmp.name, "baseline_policy.json")
        cls.cand = os.path.join(cls.tmp.name, "candidate_policy.json")
        cls.traces = os.path.join(cls.tmp.name, "traces")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_simulate_human(self):
        code, out, _err = self._run(
            ["simulate", self.base, self.cand, self.traces])
        self.assertEqual(code, 0)
        self.assertIn("SHADOW-MODE POLICY SIMULATION", out)
        self.assertIn("refunds over $200 need approval", out)

    def test_simulate_json(self):
        code, out, _err = self._run(
            ["simulate", self.base, self.cand, self.traces, "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["summary"]["new_denials"], 2)
        self.assertEqual(payload["summary"]["new_approvals"], 7)

    def test_diff(self):
        code, out, _err = self._run(
            ["diff", self.base, self.cand, self.traces, "--trace", "t-002"])
        self.assertEqual(code, 0)
        self.assertIn("2 changed steps", out)
        self.assertIn("approval_to_deny", out)

    def test_diff_unknown_trace(self):
        code, _out, _err = self._run(
            ["diff", self.base, self.cand, self.traces, "--trace", "nope"])
        self.assertEqual(code, 2)

    def test_check_violations_exit2(self):
        # default gates: 2/30 denials = 6.7% > 5% -> error
        code, _out, err = self._run(["check", self.base, self.cand, self.traces])
        self.assertEqual(code, 2)
        self.assertIn("new denial rate", err)

    def test_check_loose_gates_exit1_warning(self):
        # gates loose enough for denials/approvals, but t-002 still stalls
        code, _out, err = self._run([
            "check", self.base, self.cand, self.traces,
            "--max-new-deny-rate", "0.10", "--max-new-approval-rate", "0.30"])
        self.assertEqual(code, 1)
        self.assertIn("would stall", err)

    def test_check_identical_policies_exit0(self):
        code, _out, _err = self._run(
            ["check", self.base, self.base, self.traces])
        self.assertEqual(code, 0)

    def test_check_forbid_pattern(self):
        code, _out, err = self._run([
            "check", self.base, self.cand, self.traces,
            "--max-new-deny-rate", "1.0", "--max-new-approval-rate", "1.0",
            "--forbid-new-deny-on", "billing.*"])
        self.assertEqual(code, 2)
        self.assertIn("billing.*", err)

    def test_demo(self):
        code, out, _err = self._run(["demo"])
        self.assertEqual(code, 0)
        self.assertIn("demo OK", out)


if __name__ == "__main__":
    unittest.main()
