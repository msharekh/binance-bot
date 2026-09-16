"""Exercise dashboard ranking without starting its Streamlit application."""
import ast
from pathlib import Path
import unittest


class BuyProximityTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "dashboard.py").read_text(encoding="utf-8"))
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == "buy_proximity_score")
        self.checks = ("rsi_recovered", "near_support", "trend_ok", "reward_ok",
                       "stop_risk_ok", "momentum_ok")
        self.markets = {}
        scope = {"markets": self.markets, "buy_check_names": self.checks,
                 "max_stop_distance_threshold": .8}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "dashboard.py", "exec"), scope)
        self.score = scope["buy_proximity_score"]

    def market(self, **overrides):
        return {**dict.fromkeys(self.checks, True), "stop_distance_pct": .4,
                "ema_9": 99.5, "ema_21": 100, **overrides}

    def test_momentum_gap_breaks_alphabetical_tie(self):
        self.markets.update(A_FAR=self.market(momentum_ok=False, ema_9=90),
                            Z_NEAR=self.market(momentum_ok=False))
        self.assertEqual(sorted(self.markets, key=lambda s: (-self.score(s), s)),
                         ["Z_NEAR", "A_FAR"])
        self.assertAlmostEqual(self.score("A_FAR"), 5.9)
        self.assertAlmostEqual(self.score("Z_NEAR"), 5.99)

    def test_stop_distance_does_not_change_momentum_score(self):
        self.markets["A"] = self.market(momentum_ok=False, ema_9=90)
        before = self.score("A")
        self.markets["A"].pop("stop_distance_pct")
        self.assertEqual(self.score("A"), before)

    def test_missing_or_invalid_momentum_data_gets_no_credit(self):
        for value in (None, 0, -1, "invalid"):
            with self.subTest(ema_21=value):
                self.markets["A"] = self.market(momentum_ok=False, ema_21=value)
                self.assertEqual(self.score("A"), 5)
        self.markets["A"].pop("ema_21")
        self.assertEqual(self.score("A"), 5)

    def test_stop_risk_formula_and_all_pass_are_preserved(self):
        self.markets["A"] = self.market(stop_risk_ok=False, stop_distance_pct=1.6)
        self.assertEqual(self.score("A"), 5.5)
        self.markets["A"] = self.market()
        self.assertEqual(self.score("A"), 6)
