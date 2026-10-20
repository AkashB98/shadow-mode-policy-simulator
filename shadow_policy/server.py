"""Tiny JSON API for the simulator (stdlib http.server, 127.0.0.1 only).

POST /simulate
    {"baseline": {...policy json...}, "candidate": {...}, "traces": [[{...trace jsonl lines...}], ...]}
    -> {"summary": {...}, "driving_rules": [...], ...}   (Simulation.to_dict)

GET  /health -> {"ok": true}
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List

from .policy import Policy
from .traces import Trace, Step
from .simulate import run


def _policy_from_obj(obj: Dict[str, Any], name: str) -> Policy:
    return Policy(
        name=obj.get("name", name),
        default_action=obj.get("default_action", "require_approval"),
        rules=obj.get("rules", []),
    )


def _traces_from_obj(objs: List[List[Dict[str, Any]]]) -> List[Trace]:
    out = []
    for i, lines in enumerate(objs):
        meta = next((l for l in lines if l.get("kind") == "meta"), {})
        steps = [Step(seq=int(l.get("seq", j)), tool=str(l["tool"]),
                      args=dict(l.get("args") or {}))
                 for j, l in enumerate(lines) if l.get("kind") == "step"]
        out.append(Trace(trace_id=str(meta.get("trace_id", f"api-trace-{i}")),
                         scenario=str(meta.get("scenario", "")),
                         steps=steps))
    return out


class _Handler(BaseHTTPRequestHandler):
    server_version = "ShadowPolicySim/1.0"

    def _send(self, code: int, obj: Any) -> None:
        body = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/simulate":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            baseline = _policy_from_obj(payload["baseline"], "baseline")
            candidate = _policy_from_obj(payload["candidate"], "candidate")
            traces = _traces_from_obj(payload["traces"])
            sim = run(baseline, candidate, traces)
            self._send(200, sim.to_dict())
        except (KeyError, ValueError, TypeError) as exc:
            self._send(400, {"error": f"bad request: {exc}"})

    def log_message(self, *a):  # noqa: ANN001, ANN202
        pass


def serve(port: int = 8473) -> None:
    HTTPServer(("127.0.0.1", port), _Handler).serve_forever()
