#!/usr/bin/env python3
"""End-to-end demo: build fixtures, run the sim, smoke-test the live API.

One command, asserts inline — this is the demo path a reviewer runs:

    python3 demo.py

Asserts the documented headline (30 steps / 7 new approvals / 2 new denials /
1 stalled trace), then starts the JSON API on 127.0.0.1, POSTs the same
scenario over HTTP, and asserts the server agrees with the in-process run.
"""

import http.client
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shadow_policy import demo_scenario, render  # noqa: E402
from shadow_policy.server import _Handler  # noqa: E402
from http.server import HTTPServer  # noqa: E402

PORT = 8473


def main() -> int:
    # 1) in-process scenario
    sim, ctx = demo_scenario.run()
    s = sim.summary()
    assert s["steps"] == 30, s
    assert s["traces"] == 5, s
    assert s["new_approvals"] == 7, s
    assert s["new_denials"] == 2, s
    assert s["traces_stalled"] == 1, s
    assert s["new_denial_rate"] == round(2 / 30, 4), s
    assert sim.driving_rules()[0]["rule"] == "refunds over $200 need approval"
    print(render(sim), end="")

    # 2) live localhost round-trip over the JSON API
    server = HTTPServer(("127.0.0.1", PORT), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload_lines = []
        from shadow_policy.demo_scenario import (
            BASELINE_POLICY, CANDIDATE_POLICY, _TRACE_SCRIPTS, trace_to_jsonl,
        )
        traces = []
        for trace_id, scenario, script in _TRACE_SCRIPTS:
            lines = [json.loads(line)
                     for line in trace_to_jsonl(trace_id, scenario, script).splitlines()]
            traces.append(lines)
        body = json.dumps({
            "baseline": BASELINE_POLICY,
            "candidate": CANDIDATE_POLICY,
            "traces": traces,
        }).encode()

        for _ in range(50):
            try:
                conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=2)
                conn.request("GET", "/health")
                if conn.getresponse().status == 200:
                    break
            except OSError:
                time.sleep(0.05)

        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("POST", "/simulate", body,
                     {"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200, resp.status
        api = json.loads(resp.read().decode())
        assert api["summary"]["new_denials"] == 2, api["summary"]
        assert api["summary"]["new_approvals"] == 7, api["summary"]
        assert api["summary"]["steps"] == 30, api["summary"]
        print(f"demo OK: in-process == live API ({len(traces)} traces over HTTP)")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
