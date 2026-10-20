"""Trace loading in the tool-call-trace-replay JSONL format.

A trace file is one JSON object per line: the first line is the trace
metadata header (``kind: "meta"``), every following line is a step
(``kind: "step"``) with ``seq``, ``tool`` and ``args``. Volatile fields
(timestamps, request ids, measured durations) are stripped — simulating
policy decisions compares *behavior*, not clock noise.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List


@dataclass
class Step:
    seq: int
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    trace_id: str
    scenario: str = ""
    steps: List[Step] = field(default_factory=list)


def load_trace_file(path: str) -> Trace:
    """Load one trace JSONL file. Raises ValueError on malformed input."""
    steps: List[Step] = []
    meta: Dict[str, Any] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: bad JSON: {exc}") from exc
            kind = obj.get("kind")
            if lineno == 1 and kind == "meta":
                meta = obj
                continue
            if kind == "meta":
                # tolerate meta anywhere (e.g. concatenated files); keep first
                if not meta:
                    meta = obj
                continue
            if kind != "step":
                raise ValueError(f"{path}:{lineno}: expected kind 'step', got {kind!r}")
            if "tool" not in obj:
                raise ValueError(f"{path}:{lineno}: step missing 'tool'")
            steps.append(
                Step(
                    seq=int(obj.get("seq", len(steps))),
                    tool=str(obj["tool"]),
                    args=dict(obj.get("args") or {}),
                )
            )
    trace_id = str(meta.get("trace_id", os.path.basename(path)))
    return Trace(trace_id=trace_id, scenario=str(meta.get("scenario", "")), steps=steps)


def load_traces(source: str) -> List[Trace]:
    """Load traces from a directory of ``*.jsonl`` files or a single file.

    Files are processed in sorted name order for determinism.
    """
    if os.path.isdir(source):
        paths = sorted(glob.glob(os.path.join(source, "*.jsonl")))
    else:
        paths = [source]
    if not paths:
        raise ValueError(f"no trace files found at {source}")
    return [load_trace_file(p) for p in paths]


def trace_paths(source: str) -> List[str]:
    """File paths load_traces() would read, sorted. Used by the CLI."""
    if os.path.isdir(source):
        return sorted(glob.glob(os.path.join(source, "*.jsonl")))
    return [source]
