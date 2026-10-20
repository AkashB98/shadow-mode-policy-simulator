#!/usr/bin/env python3
"""CLI for shadow-mode-policy-simulator.

Usage:
    python3 shadow_policy/cli.py simulate BASELINE CANDIDATE TRACES [--format human|json]
    python3 shadow_policy/cli.py diff      BASELINE CANDIDATE TRACES [--trace ID]
    python3 shadow_policy/cli.py check     BASELINE CANDIDATE TRACES [gates...]
    python3 shadow_policy/cli.py demo
    python3 shadow_policy/cli.py serve [--port 8473]

check exit codes: 0 = within gates, 1 = warnings, 2 = gate violations.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_policy import (  # noqa: E402
    load_policy, load_traces, run, render, DELTA_SEVERITY,
)


def _load_all(baseline_path: str, candidate_path: str, traces_path: str):
    baseline = load_policy(baseline_path)
    candidate = load_policy(candidate_path)
    traces = load_traces(traces_path)
    return baseline, candidate, traces


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_simulate(args: argparse.Namespace) -> int:
    baseline, candidate, traces = _load_all(args.baseline, args.candidate, args.traces)
    sim = run(baseline, candidate, traces)
    if args.format == "json":
        print(json.dumps(sim.to_dict(), indent=2, sort_keys=True, default=str))
    else:
        print(render(sim), end="")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    baseline, candidate, traces = _load_all(args.baseline, args.candidate, args.traces)
    if args.trace:
        traces = [t for t in traces if t.trace_id == args.trace]
        if not traces:
            print(f"no trace with id {args.trace!r}", file=sys.stderr)
            return 2
    sim = run(baseline, candidate, traces)
    changed = sim.changed_steps
    print(f"{len(changed)} changed steps of {sim.total_steps}:")
    for s in changed:
        sev = DELTA_SEVERITY[s.delta]
        args_preview = json.dumps(s.args, sort_keys=True)[:72]
        print(f"  [{sev:9s}] {s.delta:18s} {s.trace_id}#{s.seq} {s.tool} {args_preview}")
        print(f"              {s.old_action} ({s.old_rule}) -> "
              f"{s.new_action} ({s.new_rule})")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """CI gate over the simulation. 0 clean / 1 warnings / 2 violations."""
    baseline, candidate, traces = _load_all(args.baseline, args.candidate, args.traces)
    sim = run(baseline, candidate, traces)
    s = sim.summary()
    errors, warnings = [], []

    if s["new_denial_rate"] > args.max_new_deny_rate:
        errors.append(
            f"new denial rate {s['new_denial_rate']:.1%} exceeds "
            f"--max-new-deny-rate {args.max_new_deny_rate:.1%}")
    if s["new_approval_rate"] > args.max_new_approval_rate:
        errors.append(
            f"new approval rate {s['new_approval_rate']:.1%} exceeds "
            f"--max-new-approval-rate {args.max_new_approval_rate:.1%}")

    for pattern in args.forbid_new_deny_on or []:
        hits = [st for st in sim.changed_steps
                if st.delta in ("allow_to_deny", "approval_to_deny")
                and fnmatch.fnmatch(st.tool, pattern)]
        if hits:
            errors.append(
                f"newly denied steps on protected tool pattern {pattern!r}: "
                f"{len(hits)} (e.g. {hits[0].tool})")

    if s["traces_stalled"]:
        warnings.append(f"{s['traces_stalled']} trace(s) would stall under the candidate policy")

    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)
    print(f"check: {s['steps']} steps, {s['new_denials']} new denials, "
          f"{s['new_approvals']} new approvals, "
          f"{s['traces_stalled']} stalled traces")
    if errors:
        return 2
    if warnings:
        return 1
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """In-process end-to-end demo with inline asserts. No network."""
    from shadow_policy import demo_scenario
    sim, ctx = demo_scenario.run()
    s = sim.summary()
    # headline asserts: the fixture policies were designed for exact deltas
    assert s["new_denials"] == 2, s
    assert s["new_approvals"] == 7, s
    assert s["traces_stalled"] == 1, s
    assert s["changed_rate"] > 0.10, s
    top = sim.driving_rules()[0]
    assert top["rule"] == "refunds over $200 need approval", top
    print(render(sim), end="")
    print(f"demo OK: {ctx['traces']} traces, {s['steps']} steps, "
          f"{len(sim.changed_steps)} changed — asserts passed")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from shadow_policy.server import serve
    serve(port=args.port)
    return 0


# ---------------------------------------------------------------------------
# arg parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shadow-policy",
                                description="shadow-mode policy simulator")
    sub = p.add_subparsers(dest="command", required=True)

    def _add_paths(sp):
        sp.add_argument("baseline", help="baseline policy JSON (what is live)")
        sp.add_argument("candidate", help="candidate policy JSON (proposed)")
        sp.add_argument("traces", help="trace dir or single *.jsonl trace file")
        return sp

    s = _add_paths(sub.add_parser("simulate", help="replay traces, print report"))
    s.add_argument("--format", choices=["human", "json"], default="human")
    s.set_defaults(func=cmd_simulate)

    d = _add_paths(sub.add_parser("diff", help="per-step delta table"))
    d.add_argument("--trace", default=None, help="restrict to one trace id")
    d.set_defaults(func=cmd_diff)

    c = _add_paths(sub.add_parser("check", help="CI gate: exit 0/1/2"))
    c.add_argument("--max-new-deny-rate", type=float, default=0.05)
    c.add_argument("--max-new-approval-rate", type=float, default=0.25)
    c.add_argument("--forbid-new-deny-on", action="append", default=[],
                   help="tool glob that must never gain a denial (repeatable)")
    c.set_defaults(func=cmd_check)

    dm = sub.add_parser("demo", help="end-to-end demo with inline asserts")
    dm.set_defaults(func=cmd_demo)

    sv = sub.add_parser("serve", help="JSON API on 127.0.0.1")
    sv.add_argument("--port", type=int, default=8473)
    sv.set_defaults(func=cmd_serve)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
