"""Trace loading unit tests."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_policy.traces import load_trace_file, load_traces


def write_jsonl(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


META = {"kind": "meta", "trace_id": "t-x", "scenario": "s",
        "created_at": "2026-10-20T00:00:00Z"}


def step(i, tool, args):
    return {"kind": "step", "seq": i, "observation": "obs", "tool": tool,
            "args": args, "result": {"ok": True},
            "timestamp": "2026-10-20T00:00:01Z", "request_id": "r1",
            "duration_ms": 9.9}


class TestLoadTraceFile(unittest.TestCase):
    def test_basic(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.jsonl")
            write_jsonl(p, [META, step(0, "helios.x", {"q": "k"}),
                            step(1, "billing.refund", {"amount": 5})])
            t = load_trace_file(p)
            self.assertEqual(t.trace_id, "t-x")
            self.assertEqual(t.scenario, "s")
            self.assertEqual(len(t.steps), 2)
            self.assertEqual(t.steps[1].tool, "billing.refund")
            self.assertEqual(t.steps[1].args, {"amount": 5})

    def test_volatile_fields_ignored(self):
        # timestamps / request ids / durations must not leak into steps
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.jsonl")
            write_jsonl(p, [META, step(0, "helios.x", {})])
            t = load_trace_file(p)
            self.assertFalse(hasattr(t.steps[0], "timestamp"))

    def test_meta_optional(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.jsonl")
            write_jsonl(p, [step(0, "helios.x", {})])
            t = load_trace_file(p)
            self.assertEqual(t.trace_id, "a.jsonl")

    def test_bad_kind_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.jsonl")
            write_jsonl(p, [META, {"kind": "weird"}])
            with self.assertRaises(ValueError):
                load_trace_file(p)

    def test_step_without_tool_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.jsonl")
            write_jsonl(p, [META, {"kind": "step", "seq": 0, "args": {}}])
            with self.assertRaises(ValueError):
                load_trace_file(p)


class TestLoadTracesDir(unittest.TestCase):
    def test_sorted_deterministic_order(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("b.jsonl", "a.jsonl", "c.jsonl"):
                write_jsonl(os.path.join(d, name),
                            [{"kind": "meta", "trace_id": name}, step(0, "t", {})])
            traces = load_traces(d)
            self.assertEqual([t.trace_id for t in traces],
                             ["a.jsonl", "b.jsonl", "c.jsonl"])

    def test_empty_dir_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                load_traces(d)


if __name__ == "__main__":
    unittest.main()
