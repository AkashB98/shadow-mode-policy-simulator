#!/usr/bin/env python3
"""Golden evals for shadow-mode-policy-simulator.

Runs the fixture scenario (30 steps across 5 traces, v1 -> v2 policy) and
pins the FULL delta output: headline summary, every changed step, per-tool
rollup, and driving-rule ranking. Expectations live in evals/golden.json.

The scenario is fully deterministic (hand-scripted traces, no randomness),
so eval_report.json must be byte-identical across runs — the md5 pin is the
determinism proof.

Usage: python evals/run_evals.py [--report evals/eval_report.json]
Exit 0 iff every golden eval passes.
"""

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_policy import demo_scenario, load_policy, load_traces  # noqa: E402
from shadow_policy.simulate import run  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "fixtures")


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=os.path.join(ROOT, "evals", "eval_report.json"))
    args = ap.parse_args()

    with open(os.path.join(ROOT, "evals", "golden.json"), encoding="utf-8") as fh:
        golden = json.load(fh)

    results = []

    def check(name, actual, expected):
        ok = canonical(actual) == canonical(expected)
        results.append({"name": name, "passed": ok})
        if not ok:
            results[-1]["actual"] = actual
            results[-1]["expected"] = expected
        return ok

    # Eval 1: in-memory scenario run matches the golden summary
    sim_mem, _ctx = demo_scenario.run()
    check("summary_headline", sim_mem.summary(), golden["summary"])

    # Eval 2: every changed step is pinned (trace, seq, tool, verdicts, rules)
    changed = [s.to_dict() for s in sim_mem.changed_steps]
    check("changed_steps", changed, golden["changed_steps"])

    # Eval 3: per-tool rollup pinned
    check("per_tool", sim_mem.per_tool(), golden["per_tool"])

    # Eval 4: driving-rule ranking pinned
    check("driving_rules", sim_mem.driving_rules(), golden["driving_rules"])

    # Eval 5: trace impact statuses pinned
    check("trace_impacts",
          [t.to_dict() for t in sim_mem.trace_impacts],
          golden["trace_impacts"])

    # Eval 6: file-based round trip (fixtures on disk) matches in-memory
    base = load_policy(os.path.join(FIXTURES, "baseline_policy.json"))
    cand = load_policy(os.path.join(FIXTURES, "candidate_policy.json"))
    traces = load_traces(os.path.join(FIXTURES, "traces"))
    sim_disk = run(base, cand, traces)
    check("disk_matches_memory", sim_disk.summary(), sim_mem.summary())

    # Eval 7: byte-identical determinism — two fresh runs, same canonical bytes
    sim_again, _ = demo_scenario.run()
    bytes_a = canonical(sim_mem.to_dict()).encode()
    bytes_b = canonical(sim_again.to_dict()).encode()
    check("determinism_md5",
          hashlib.md5(bytes_a).hexdigest(),
          hashlib.md5(bytes_b).hexdigest())

    report = {
        "golden": "evals/golden.json",
        "passed": all(r["passed"] for r in results),
        "evals": results,
        "summary": sim_mem.summary(),
    }
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")

    failed = [r["name"] for r in results if not r["passed"]]
    md5 = hashlib.md5(open(args.report, "rb").read()).hexdigest()
    print(f"{len(results) - len(failed)}/{len(results)} golden evals passed "
          f"(report md5 {md5})")
    for name in failed:
        print(f"  FAILED: {name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
