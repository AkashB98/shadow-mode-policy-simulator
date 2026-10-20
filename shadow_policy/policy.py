"""Policy loading and evaluation for shadow-mode simulation.

Implements the tool-approval-gate policy schema (the schema operators already
use): ordered rules, first-match-wins, fail-closed default. A tool call is
matched against a policy purely as a function of (tool name, args) — no
clocks, no approval stores, no network — which is exactly what lets us replay
a thousand historical traces against a candidate policy in milliseconds.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

VALID_ACTIONS = ("allow", "require_approval", "deny")


# ---------------------------------------------------------------------------
# dot-path resolution
# ---------------------------------------------------------------------------

def resolve_path(args: Dict[str, Any], path: str) -> tuple[bool, Any]:
    """Resolve a dotted path like ``items.0.sku`` against an args dict.

    Returns (found, value). Integer segments index into lists; anything else
    walks dict keys. A miss returns (False, None).
    """
    node: Any = args
    for seg in path.split("."):
        if isinstance(node, dict):
            if seg not in node:
                return False, None
            node = node[seg]
        elif isinstance(node, (list, tuple)) and seg.lstrip("-").isdigit():
            idx = int(seg)
            if idx < 0 or idx >= len(node):
                return False, None
            node = node[idx]
        else:
            return False, None
    return True, node


# ---------------------------------------------------------------------------
# arg matchers
# ---------------------------------------------------------------------------

def _num(x: Any) -> Optional[float]:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x))
    except (TypeError, ValueError):
        return None


def match_arg(spec: Any, value: Any) -> bool:
    """Match a single matcher spec against a resolved arg value."""
    if not isinstance(spec, dict):
        # bare value means equality
        return spec == value
    for op, operand in spec.items():
        if op == "eq":
            if not (value == operand):
                return False
        elif op == "ne":
            if not (value != operand):
                return False
        elif op == "regex":
            if not isinstance(value, str) or not re.search(str(operand), value):
                return False
        elif op == "glob":
            if not isinstance(value, str) or not fnmatch.fnmatch(value, str(operand)):
                return False
        elif op in ("gt", "gte", "lt", "lte"):
            v, o = _num(value), _num(operand)
            if v is None or o is None:
                return False
            if op == "gt" and not (v > o):
                return False
            if op == "gte" and not (v >= o):
                return False
            if op == "lt" and not (v < o):
                return False
            if op == "lte" and not (v <= o):
                return False
        elif op == "in":
            if value not in operand:
                return False
        elif op == "nin":
            if value in operand:
                return False
        elif op == "contains":
            try:
                if operand not in value:
                    return False
            except TypeError:
                return False
        elif op == "exists":
            # existence is handled by the caller; here value is always present
            if not bool(operand):
                return False
        else:
            raise ValueError(f"unknown matcher op: {op}")
    return True


def rule_matches(rule: Dict[str, Any], tool: str, args: Dict[str, Any]) -> bool:
    """True when the rule matches (tool glob + every arg matcher)."""
    if not fnmatch.fnmatch(tool, rule.get("tool", "*")):
        return False
    for path, spec in (rule.get("args") or {}).items():
        if isinstance(spec, dict) and set(spec.keys()) == {"exists"}:
            found, _ = resolve_path(args, path)
            if bool(found) != bool(spec["exists"]):
                return False
            continue
        found, value = resolve_path(args, path)
        if not found:
            # A rule about an argument that isn't there is a rule that
            # shouldn't fire. (exists:false handled above.)
            return False
        if not match_arg(spec, value):
            return False
    return True


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    action: str            # allow | require_approval | deny
    rule_name: str         # firing rule, or "(default)"
    policy_name: str = ""


@dataclass
class Policy:
    name: str
    default_action: str = "require_approval"
    rules: List[Dict[str, Any]] = field(default_factory=list)

    def evaluate(self, tool: str, args: Dict[str, Any]) -> Decision:
        """First-match-wins; fall through to the fail-closed default."""
        for rule in self.rules:
            if rule_matches(rule, tool, args):
                return Decision(
                    action=rule.get("action", "require_approval"),
                    rule_name=rule.get("name", "(unnamed)"),
                    policy_name=self.name,
                )
        return Decision(
            action=self.default_action,
            rule_name="(default)",
            policy_name=self.name,
        )


def load_policy(path: str) -> Policy:
    """Load a policy from a tool-approval-gate-format JSON file."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    name = data.get("name", path)
    default_action = data.get("default_action", "require_approval")
    if default_action not in VALID_ACTIONS:
        raise ValueError(f"policy {path}: bad default_action {default_action!r}")
    rules = data.get("rules", [])
    for i, rule in enumerate(rules):
        action = rule.get("action", "require_approval")
        if action not in VALID_ACTIONS:
            raise ValueError(f"policy {path} rule {i}: bad action {action!r}")
    return Policy(name=name, default_action=default_action, rules=rules)
