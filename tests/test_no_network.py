"""No-network guard: the whole simulation core must work with sockets ripped out."""

import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _NoSockets:
    def __init__(self, *a, **k):
        raise AssertionError("network access forbidden in hermetic tests")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestNoNetwork(unittest.TestCase):
    def test_core_flows_without_sockets(self):
        real_socket = socket.socket
        socket.socket = _NoSockets
        try:
            from shadow_policy import demo_scenario
            sim, ctx = demo_scenario.run()   # full sim, no network
            self.assertEqual(sim.summary()["steps"], 30)
            from shadow_policy import render
            text = render(sim)
            self.assertIn("SHADOW-MODE", text)
        finally:
            socket.socket = real_socket


if __name__ == "__main__":
    unittest.main()
