"""Policy matching unit tests."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_policy.policy import Policy, load_policy, rule_matches


def P(rules, default="require_approval", name="t"):
    return Policy(name=name, default_action=default, rules=rules)


class TestToolGlob(unittest.TestCase):
    def test_exact(self):
        r = {"name": "r", "tool": "billing.refund", "action": "allow"}
        self.assertTrue(rule_matches(r, "billing.refund", {}))
        self.assertFalse(rule_matches(r, "billing.charge", {}))

    def test_glob(self):
        r = {"name": "r", "tool": "helios.*", "action": "allow"}
        self.assertTrue(rule_matches(r, "helios.get_order", {}))
        self.assertFalse(rule_matches(r, "billing.refund", {}))


class TestMatchers(unittest.TestCase):
    def _r(self, path, spec):
        return {"name": "r", "tool": "*", "args": {path: spec}, "action": "allow"}

    def test_eq_ne(self):
        self.assertTrue(rule_matches(self._r("a", {"eq": 5}), "t", {"a": 5}))
        self.assertFalse(rule_matches(self._r("a", {"eq": 5}), "t", {"a": 6}))
        self.assertTrue(rule_matches(self._r("a", {"ne": 5}), "t", {"a": 6}))

    def test_numeric(self):
        r = self._r("amount", {"gt": 500})
        self.assertTrue(rule_matches(r, "t", {"amount": 501}))
        self.assertFalse(rule_matches(r, "t", {"amount": 500}))
        r = self._r("amount", {"lte": 500})
        self.assertTrue(rule_matches(r, "t", {"amount": 500}))
        self.assertFalse(rule_matches(r, "t", {"amount": 501}))
        # numeric strings coerce
        self.assertTrue(rule_matches(self._r("amount", {"gte": 10}), "t",
                                     {"amount": "10"}))
        # non-numeric never matches a numeric matcher
        self.assertFalse(rule_matches(self._r("amount", {"gt": 1}), "t",
                                      {"amount": "abc"}))

    def test_regex_glob(self):
        self.assertTrue(rule_matches(self._r("id", {"regex": r"^H-\d+$"}), "t",
                                     {"id": "H-1042"}))
        self.assertFalse(rule_matches(self._r("id", {"regex": r"^H-\d+$"}), "t",
                                       {"id": "X-1"}))
        self.assertTrue(rule_matches(self._r("q", {"glob": "kett*"}), "t",
                                     {"q": "kettle"}))

    def test_in_nin_contains(self):
        self.assertTrue(rule_matches(self._r("q", {"in": ["a", "b"]}), "t", {"q": "a"}))
        self.assertFalse(rule_matches(self._r("q", {"in": ["a", "b"]}), "t", {"q": "z"}))
        self.assertTrue(rule_matches(self._r("q", {"nin": ["a"]}), "t", {"q": "z"}))
        self.assertTrue(rule_matches(self._r("items", {"contains": "x"}), "t",
                                      {"items": ["x", "y"]}))
        self.assertTrue(rule_matches(self._r("note", {"contains": "urgent"}), "t",
                                      {"note": "this is urgent"}))

    def test_dot_path(self):
        r = self._r("customer.id", {"eq": "C-1"})
        self.assertTrue(rule_matches(r, "t", {"customer": {"id": "C-1"}}))
        self.assertFalse(rule_matches(r, "t", {"customer": {"id": "C-2"}}))
        r = self._r("items.0.sku", {"eq": "K1"})
        self.assertTrue(rule_matches(r, "t", {"items": [{"sku": "K1"}]}))
        self.assertFalse(rule_matches(r, "t", {"items": []}))

    def test_missing_path_never_fires(self):
        # A rule about an argument that isn't there must not fire —
        # except the explicit exists:false form.
        self.assertFalse(rule_matches(self._r("amount", {"gt": 1}), "t", {}))
        self.assertTrue(rule_matches(self._r("amount", {"exists": False}), "t", {}))
        self.assertFalse(rule_matches(self._r("amount", {"exists": False}), "t",
                                       {"amount": 1}))
        self.assertTrue(rule_matches(self._r("amount", {"exists": True}), "t",
                                      {"amount": 0}))
        self.assertFalse(rule_matches(self._r("amount", {"exists": True}), "t", {}))

    def test_bare_value_means_eq(self):
        self.assertTrue(rule_matches(self._r("a", 5), "t", {"a": 5}))
        self.assertFalse(rule_matches(self._r("a", 5), "t", {"a": 6}))

    def test_all_matchers_must_pass(self):
        r = {"name": "r", "tool": "*",
             "args": {"amount": {"gt": 200}, "region": {"eq": "US"}},
             "action": "allow"}
        self.assertTrue(rule_matches(r, "t", {"amount": 300, "region": "US"}))
        self.assertFalse(rule_matches(r, "t", {"amount": 300, "region": "EU"}))

    def test_unknown_op_raises(self):
        with self.assertRaises(ValueError):
            rule_matches(self._r("a", {"bogus": 1}), "t", {"a": 1})


class TestPolicyEval(unittest.TestCase):
    def test_first_match_wins(self):
        p = P([
            {"name": "deny big", "tool": "billing.refund",
             "args": {"amount": {"gt": 5000}}, "action": "deny"},
            {"name": "approve rest", "tool": "billing.refund", "action": "require_approval"},
        ])
        d = p.evaluate("billing.refund", {"amount": 9000})
        self.assertEqual((d.action, d.rule_name), ("deny", "deny big"))
        d = p.evaluate("billing.refund", {"amount": 100})
        self.assertEqual((d.action, d.rule_name), ("require_approval", "approve rest"))

    def test_default_fail_closed(self):
        p = P([])
        d = p.evaluate("unknown.tool", {})
        self.assertEqual((d.action, d.rule_name),
                         ("require_approval", "(default)"))

    def test_load_policy(self):
        import json, tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"name": "x", "default_action": "deny", "rules": [
                {"name": "r1", "tool": "a.*", "action": "allow"}]}, fh)
            path = fh.name
        p = load_policy(path)
        self.assertEqual(p.name, "x")
        self.assertEqual(p.evaluate("a.b", {}).action, "allow")
        self.assertEqual(p.evaluate("z", {}).action, "deny")
        os.unlink(path)

    def test_load_policy_bad_action_rejected(self):
        import json, tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"rules": [{"name": "r", "tool": "*", "action": "explode"}]},
                      fh)
            path = fh.name
        with self.assertRaises(ValueError):
            load_policy(path)
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
