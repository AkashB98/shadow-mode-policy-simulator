# shadow-mode-policy-simulator

**Dry-run an approval-policy change against historical agent traffic before it
goes live.** Every policy change is a deployment; this is the canary.

Point it at a baseline policy (what's live today), a candidate policy (the
proposed change), and a directory of recorded agent traces — it replays every
tool call under both policies and reports the blast radius: how many steps
gain friction, how many get newly denied, which traces would stall, and —
the part operators actually need — **which rule caused it**.

## Why this exists (the hiring signal)

Every team shipping agents to customers runs a human-in-the-loop approval
policy (`tool-approval-gate` is the engine). And every policy change is
currently deployed blind: someone edits the JSON on a Friday, and Monday
morning the support queue has 3x the approvals and one fraud-review flow is
silently dead. This is the CI step that should have existed — **policy
changes get the same change-impact analysis as code changes**: replay
yesterday's traffic against the new policy in shadow mode, diff the verdicts,
gate the rollout.

It completes the sibling story: lint the schemas (`tool-schema-linter`), pin
versions (`tool-contract-checker`), fuzz the args (`tool-arg-fuzzer`),
red-team the safety (`ai-red-teaming-harness`), replay golden traces
(`tool-call-trace-replay`), gate the dangerous calls (`tool-approval-gate`) —
and now **preview every gate change before it ships**.

## Quickstart

```bash
python3 shadow_policy/cli.py demo        # end-to-end scenario, asserts inline
python3 shadow_policy/cli.py simulate fixtures/baseline_policy.json \
    fixtures/candidate_policy.json fixtures/traces
python3 shadow_policy/cli.py diff fixtures/baseline_policy.json \
    fixtures/candidate_policy.json fixtures/traces --trace t-002
python3 shadow_policy/cli.py check fixtures/baseline_policy.json \
    fixtures/candidate_policy.json fixtures/traces   # CI gate, exit 0/1/2
python3 shadow_policy/cli.py serve --port 8473       # JSON API on 127.0.0.1
```

`demo` replays a scripted week of a fictional Helios Home support agent
(5 traces, 30 steps) against a tightened refund/shipment policy and asserts
the exact headline. `python3 demo.py` does the same plus a live localhost
`/simulate` round-trip.

## What it computes

For every step, both policies are evaluated (ordered rules, first-match-wins,
fail-closed default — the `tool-approval-gate` schema: tool globs, dot-path
arg matchers `eq ne regex glob gt gte lt lte in nin exists contains`) and the
verdict pair is classified:

| delta | meaning |
|---|---|
| `allow_to_approval` | NEW FRICTION — was instant, now needs a human |
| `allow_to_deny` / `approval_to_deny` | NEW BLOCK — now refused |
| `approval_to_allow` | NEW AUTOMATION — approval queue shrinks |
| `deny_to_allow` / `deny_to_approval` | LOOSENED |
| `unchanged` | no behavior change on this step |

Aggregates: per-tool rollup, **driving rules** (candidate rules ranked by how
many verdicts they changed — the rule to review, split, or roll back), and
trace-level impact: `clean` / `changed` / `stalls` (≥1 newly denied step).

`check` is the CI gate: `--max-new-deny-rate`, `--max-new-approval-rate`,
and repeatable `--forbid-new-deny-on` tool globs (e.g. never newly deny
`billing.*`). Exit 0 clean, 1 warnings (traces would stall), 2 violations.

## Inputs

- **Policies**: JSON in the `tool-approval-gate` policy format
  (`{"name", "default_action", "rules": [{"name", "tool" (glob), "args"
  (dot-path matchers), "action"}]}`). `exists:false` matchers supported; a
  matcher on a missing path never fires (except `exists:false`).
- **Traces**: JSONL in the `tool-call-trace-replay` format — first line
  `{"kind": "meta", ...}`, then `{"kind": "step", "seq", "tool", "args",
  ...}` lines. Volatile fields (timestamps, request ids, durations) are
  ignored: simulation compares behavior, not clock noise.

## The fixture story

`shadow_policy/demo_scenario.py` scripts the narrative: finance tightened the
screws — refunds over $200 now need approval (was $500), 5+ unit shipments
escalate (was 10+), refunds over $5000 are refused outright.

```
  allow -> approval (NEW FRICTION)         7   23.3%
  approval -> deny (NEW BLOCK)             2    6.7%
  unchanged                              21   70.0%
  traces that would stall: 1 / 5   (t-002: two $6k+ reseller refunds denied)
  top driving rule: "refunds over $200 need approval" (4 steps)
```

The report tells ops exactly what the policy edit costs: 7 new human
approvals per 30 steps, one fraud-review flow dead, and the single rule to
reconsider.

## Project layout

```
shadow_policy/
  policy.py         policy loading + evaluation (glob, dot-path matchers)
  traces.py         trace-replay JSONL loading (volatile fields stripped)
  simulate.py       dual evaluation, delta taxonomy, rollups, driving rules
  demo_scenario.py  scripted fixture scenario (policies + 5 traces)
  report.py         human-readable blast-radius report
  server.py         stdlib JSON API (POST /simulate) on 127.0.0.1
  cli.py            simulate / diff / check / demo / serve
fixtures/           baseline_policy.json, candidate_policy.json, traces/*.jsonl
tests/              42 hermetic unit tests (stdlib unittest, no network)
evals/              7 golden evals, pinned in golden.json; eval_report.json
                    byte-identical across runs (md5 0f97ed89554e91af3d5221b6c5a1edde)
demo.py             end-to-end: in-process asserts + live localhost API round-trip
```

Stdlib only. No network in tests, evals, or the demo scenario (the live
localhost smoke test is opt-in inside `demo.py`). Sample data only — the
Helios Home store is fictional.

## Dev loop (bugs the tests caught)

- `demo_scenario.run()` shadowed the imported `run` from `simulate` — the
  call inside would have recursed forever. Renamed the import to
  `run_simulation`.
- `cli diff` printed only the severity bucket (`[block]`) for each changed
  step — which conflates `allow_to_deny` and `approval_to_deny`. `test_cli`
  failed on the missing label; the delta label is now printed on every line.
- Golden evals pinned the fixture headline, and the first `simulate` run
  confirmed the hand-computed numbers (30 steps / 7 frictions / 2 blocks /
  t-002 stalls) before they were frozen into `golden.json`.
