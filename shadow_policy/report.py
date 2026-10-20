"""Human-readable rendering of a shadow-mode Simulation."""

from __future__ import annotations

from .simulate import Simulation

_BAR_WIDTH = 40


def _bar(frac: float) -> str:
    filled = int(round(frac * _BAR_WIDTH))
    return "#" * filled + "-" * (_BAR_WIDTH - filled)


def render(sim: Simulation) -> str:
    """Multi-section text report of the policy change's blast radius."""
    s = sim.summary()
    lines = []
    lines.append("=" * 72)
    lines.append("SHADOW-MODE POLICY SIMULATION")
    lines.append(f"  baseline : {s['baseline']}")
    lines.append(f"  candidate: {s['candidate']}")
    lines.append(f"  replayed : {s['traces']} traces, {s['steps']} tool-call steps")
    lines.append("=" * 72)

    # --- headline delta counts ---
    counts = s["delta_counts"]
    lines.append("")
    lines.append("VERDICT DELTAS (baseline -> candidate)")
    rows = [
        ("allow -> approval (NEW FRICTION)", counts["allow_to_approval"]),
        ("allow -> deny (NEW BLOCK)", counts["allow_to_deny"]),
        ("approval -> allow (NEW AUTOMATION)", counts["approval_to_allow"]),
        ("approval -> deny (NEW BLOCK)", counts["approval_to_deny"]),
        ("deny -> allow (LOOSENED)", counts["deny_to_allow"]),
        ("deny -> approval (LOOSENED)", counts["deny_to_approval"]),
        ("unchanged", counts["unchanged"]),
    ]
    for label, n in rows:
        frac = n / s["steps"] if s["steps"] else 0.0
        lines.append(f"  {label:36s} {n:5d}  {frac:6.1%}  {_bar(frac)}")

    lines.append("")
    lines.append("HEADLINE")
    lines.append(f"  new approvals needed : {s['new_approvals']} ({s['new_approval_rate']:.1%} of steps)")
    lines.append(f"  newly denied steps   : {s['new_denials']} ({s['new_denial_rate']:.1%} of steps)")
    lines.append(f"  steps automated away : {s['new_automations']}")
    lines.append(f"  steps loosened       : {s['loosened']}")
    lines.append(f"  traces that would stall: {s['traces_stalled']} / {s['traces']}")
    lines.append(f"  traces changed / clean : {s['traces_changed']} / {s['traces_clean']}")

    # --- driving rules: the blast radius by rule ---
    lines.append("")
    lines.append("DRIVING RULES (candidate rules ranked by changed steps)")
    driving = sim.driving_rules()
    if not driving:
        lines.append("  (no rule changed any verdict — policies are equivalent on this traffic)")
    for d in driving:
        lines.append(f"  {d['rule']:45s} {d['changed_steps']:4d} steps "
                     f"(e.g. {d['example']['tool']} {d['example']['delta']})")

    # --- per-tool rollup ---
    lines.append("")
    lines.append("PER-TOOL BREAKDOWN (tools with at least one changed step)")
    per_tool = sim.per_tool()
    shown = [t for t in per_tool
             if any(v for k, v in per_tool[t].items() if k != "unchanged")]
    if not shown:
        lines.append("  (no tool changed behavior)")
    for tool in shown:
        deltas = per_tool[tool]
        parts = [f"{k}={v}" for k, v in sorted(deltas.items()) if k != "unchanged"]
        total = sum(deltas.values())
        lines.append(f"  {tool:32s} {total:4d} steps   " + ", ".join(parts))

    # --- stalled traces ---
    stalled = [t for t in sim.trace_impacts if t.status == "stalls"]
    if stalled:
        lines.append("")
        lines.append("TRACES THAT WOULD STALL (>=1 newly denied step)")
        for t in stalled:
            lines.append(f"  {t.trace_id}: {t.new_denials} denied, "
                         f"{t.new_approvals} new approvals of {t.steps} steps")

    lines.append("")
    return "\n".join(lines)
