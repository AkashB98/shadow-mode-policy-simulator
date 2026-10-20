"""Seeded fixture scenario for the simulator's demo and evals.

A fictional Helios Home support agent's week of tool calls, replayed against
two policies:

- **v1 (baseline, live today):** routine refunds <= $500 and small shipments
  (< 10 units) auto-approve; bigger refunds/shipments need a human.
- **v2 (candidate):** finance tightened the screws — refunds over $200 need
  approval, shipments of 5+ units escalate, and refunds over $5000 are
  refused outright (manual review channel instead).

The five traces are hand-scripted so every delta is explainable:

- t-001 routine refund day: 2 new frictions (a $350 refund and an 8-unit
  shipment now need approval)
- t-002 fraud review: 2 refunds newly DENIED ($8200, $6400) -> trace stalls
- t-003 mid-refund batch: 4 new frictions (refunds $450/$275/$499, shipment 6)
- t-004 bulk ship day: 1 new friction (7-unit shipment)
- t-005 clean day: nothing changes

Expected headline: 30 steps, 7 new approvals, 2 new denials, 1 stalled trace,
top driving rule "refunds over $200 need approval".
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

from .policy import Policy
from .traces import Trace, Step
from .simulate import Simulation
from .simulate import run as run_simulation

BASELINE_POLICY: Dict[str, Any] = {
    "name": "helios support policy v1 (live)",
    "default_action": "require_approval",
    "rules": [
        {"name": "read-only store tools", "tool": "helios.*", "action": "allow"},
        {"name": "routine refunds auto-approved",
         "tool": "billing.refund", "args": {"amount": {"lte": 500}},
         "action": "allow"},
        {"name": "big refunds need approval",
         "tool": "billing.refund", "args": {"amount": {"gt": 500}},
         "action": "require_approval", "ttl_seconds": 300, "on_timeout": "deny"},
        {"name": "small shipments auto-approved",
         "tool": "warehouse.ship_high_value", "args": {"qty": {"lt": 10}},
         "action": "allow"},
        {"name": "bulk shipments escalate",
         "tool": "warehouse.ship_high_value", "args": {"qty": {"gte": 10}},
         "action": "require_approval", "ttl_seconds": 120,
         "on_timeout": "escalate"},
    ],
}

CANDIDATE_POLICY: Dict[str, Any] = {
    "name": "helios support policy v2 (tighter)",
    "default_action": "require_approval",
    "rules": [
        {"name": "read-only store tools", "tool": "helios.*", "action": "allow"},
        {"name": "tiny refunds auto-approved",
         "tool": "billing.refund", "args": {"amount": {"lte": 200}},
         "action": "allow"},
        {"name": "huge refunds refused",
         "tool": "billing.refund", "args": {"amount": {"gt": 5000}},
         "action": "deny"},
        {"name": "refunds over $200 need approval",
         "tool": "billing.refund", "args": {"amount": {"gt": 200}},
         "action": "require_approval", "ttl_seconds": 300, "on_timeout": "deny"},
        {"name": "small parcels auto-approved",
         "tool": "warehouse.ship_high_value", "args": {"qty": {"lt": 5}},
         "action": "allow"},
        {"name": "bulk shipments escalate sooner",
         "tool": "warehouse.ship_high_value", "args": {"qty": {"gte": 5}},
         "action": "require_approval", "ttl_seconds": 120,
         "on_timeout": "escalate"},
    ],
}

# (trace_id, scenario, [(observation, tool, args)])
_TRACE_SCRIPTS: List[Tuple[str, str, List[Tuple[str, str, Dict[str, Any]]]]] = [
    ("t-001", "routine refund day", [
        ("customer asks about the kettle", "helios.search_products", {"q": "kettle"}),
        ("look up the order", "helios.get_order", {"order_id": "H-1042"}),
        ("issue the small refund", "billing.refund",
         {"amount": 120, "order_id": "H-1042"}),
        ("issue the mid refund", "billing.refund",
         {"amount": 350, "order_id": "H-1043"}),
        ("confirm the mid refund landed", "helios.get_order", {"order_id": "H-1043"}),
        ("ship the replacement parts", "warehouse.ship_high_value",
         {"qty": 3, "order_id": "H-1044"}),
        ("ship the accessory bundle", "warehouse.ship_high_value",
         {"qty": 8, "order_id": "H-1045"}),
        ("note the customer's address", "helios.order_lookup", {"customer": "C-22"}),
    ]),
    ("t-002", "fraud review", [
        ("pull the flagged order", "helios.get_order", {"order_id": "H-2010"}),
        ("refund the duplicate charge", "billing.refund",
         {"amount": 2500, "order_id": "H-2010"}),
        ("refund the reseller's bulk claim", "billing.refund",
         {"amount": 8200, "order_id": "H-2011"}),
        ("hold the reseller's shipment", "warehouse.ship_high_value",
         {"qty": 12, "order_id": "H-2012"}),
        ("search the product catalog", "helios.search_products", {"q": "lamp"}),
        ("refund the second reseller claim", "billing.refund",
         {"amount": 6400, "order_id": "H-2013"}),
    ]),
    ("t-003", "mid-refund batch", [
        ("batch refund one", "billing.refund", {"amount": 450, "order_id": "H-3010"}),
        ("batch refund two", "billing.refund", {"amount": 275, "order_id": "H-3011"}),
        ("batch refund three", "billing.refund", {"amount": 90, "order_id": "H-3012"}),
        ("verify the batch", "helios.get_order", {"order_id": "H-3010"}),
        ("ship the batch replacements", "warehouse.ship_high_value",
         {"qty": 6, "order_id": "H-3013"}),
        ("ship the single part", "warehouse.ship_high_value",
         {"qty": 2, "order_id": "H-3014"}),
        ("batch refund four", "billing.refund", {"amount": 499, "order_id": "H-3015"}),
    ]),
    ("t-004", "bulk ship day", [
        ("ship the warehouse order", "warehouse.ship_high_value",
         {"qty": 15, "order_id": "H-4010"}),
        ("ship the restock", "warehouse.ship_high_value",
         {"qty": 7, "order_id": "H-4011"}),
        ("ship the display units", "warehouse.ship_high_value",
         {"qty": 4, "order_id": "H-4012"}),
        ("check stock after shipping", "helios.search_products", {"q": "shelf"}),
        ("ship the overflow pallet", "warehouse.ship_high_value",
         {"qty": 25, "order_id": "H-4013"}),
    ]),
    ("t-005", "clean day", [
        ("browse the catalog", "helios.search_products", {"q": "mug"}),
        ("look up an order", "helios.get_order", {"order_id": "H-3050"}),
        ("tiny goodwill refund", "billing.refund", {"amount": 45, "order_id": "H-3050"}),
        ("ship the mug", "warehouse.ship_high_value", {"qty": 1, "order_id": "H-3051"}),
    ]),
]


def _policy_from_dict(d: Dict[str, Any]) -> Policy:
    return Policy(name=d["name"],
                  default_action=d.get("default_action", "require_approval"),
                  rules=d.get("rules", []))


def build_traces() -> List[Trace]:
    """Build the fixture traces in memory (no files, no randomness)."""
    traces = []
    for trace_id, scenario, script in _TRACE_SCRIPTS:
        steps = [Step(seq=i, tool=tool, args=args)
                 for i, (_obs, tool, args) in enumerate(script)]
        traces.append(Trace(trace_id=trace_id, scenario=scenario, steps=steps))
    return traces


def trace_to_jsonl(trace_id: str, scenario: str,
                   script: List[Tuple[str, str, Dict[str, Any]]]) -> str:
    """Serialize one scripted trace in tool-call-trace-replay JSONL format."""
    lines = [json.dumps({"kind": "meta", "trace_id": trace_id,
                         "scenario": scenario,
                         "created_at": "2026-10-20T00:00:00Z"},
                        sort_keys=True)]
    for i, (obs, tool, args) in enumerate(script):
        lines.append(json.dumps({
            "kind": "step", "seq": i, "observation": obs, "tool": tool,
            "args": args, "result": {"ok": True},
            "timestamp": "2026-10-20T00:00:01Z",
            "request_id": f"req-{trace_id}-{i}",
            "duration_ms": 12.5,
        }, sort_keys=True))
    return "\n".join(lines) + "\n"


def write_fixtures(root: str) -> Dict[str, str]:
    """Write fixtures/baseline_policy.json, candidate_policy.json, traces/."""
    os.makedirs(os.path.join(root, "traces"), exist_ok=True)
    paths = {}
    for name, policy in (("baseline_policy.json", BASELINE_POLICY),
                         ("candidate_policy.json", CANDIDATE_POLICY)):
        p = os.path.join(root, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(policy, fh, indent=2, sort_keys=True)
            fh.write("\n")
        paths[name] = p
    for trace_id, scenario, script in _TRACE_SCRIPTS:
        p = os.path.join(root, "traces", f"{trace_id}.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(trace_to_jsonl(trace_id, scenario, script))
        paths[f"traces/{trace_id}.jsonl"] = p
    return paths


def run() -> Tuple[Simulation, Dict[str, Any]]:
    """Run the fixture scenario in memory. Returns (simulation, context)."""
    baseline = _policy_from_dict(BASELINE_POLICY)
    candidate = _policy_from_dict(CANDIDATE_POLICY)
    traces = build_traces()
    return run_simulation(baseline, candidate, traces), {"traces": len(traces)}
