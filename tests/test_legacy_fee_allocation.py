import ast
from bisect import bisect_right
from datetime import datetime
from pathlib import Path
import unittest

import pandas as pd


class LegacyFeeAllocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "dashboard.py").read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "transaction_frame")
        scope = dict(pd=pd, datetime=datetime, bisect_right=bisect_right,
                     read_market_overview_history=lambda: [],
                     read_json=lambda *args: {"estimated_round_trip_fee_pct": .2},
                     CONFIG_FILE=None)
        exec(compile(ast.Module(body=[function], type_ignores=[]), "dashboard.py", "exec"), scope)
        cls.frame = staticmethod(scope["transaction_frame"])

    def row(self, time, side, value, quantity, pnl=None, **extra):
        return dict(recorded_at=time, side=side, symbol="ABCUSDT", environment="production",
                    quote_amount=value, quantity=quantity, estimated_pnl_usdt=pnl, **extra)

    def test_buy_more_close_and_new_trade(self):
        rows = [self.row(1, "BUY", 100, 10), self.row(2, "BUY", 200, 20),
                self.row(3, "SELL", 310, 30, 10), self.row(4, "BUY", 50, 5),
                self.row(5, "SELL", 55, 5, 5)]
        result = self.frame(rows)
        self.assertAlmostEqual(result.iloc[2]["Net P&L (USDT)"], 9.39)
        self.assertAlmostEqual(result.iloc[4]["Net P&L (USDT)"], 4.895)
        reverse = self.frame(list(reversed(rows)))
        self.assertAlmostEqual(reverse.iloc[0]["Net P&L (USDT)"], 4.895)

    def test_explicit_partial_sale_retains_proportional_fee(self):
        rows = [self.row(1, "BUY", 100, 10), self.row(2, "BUY", 200, 20),
                self.row(3, "SELL", 110, 10, 10, remaining_quantity="20", remaining_is_dust=False),
                self.row(4, "SELL", 220, 20, 20, remaining_quantity="0")]
        result = self.frame(rows)
        self.assertAlmostEqual(result.iloc[2]["Net P&L (USDT)"], 9.79)
        self.assertAlmostEqual(result.iloc[3]["Net P&L (USDT)"], 19.58)

    def test_legacy_close_with_dust_does_not_strand_fees(self):
        rows = [self.row(1, "BUY", 100, 10), self.row(2, "BUY", 200, 20),
                self.row(3, "SELL", 310, 29.99, 10),
                self.row(4, "SELL", 55, 5, 5)]
        self.assertAlmostEqual(self.frame(rows).iloc[3]["Net P&L (USDT)"], 4.945)

    def test_environment_isolation_and_recorded_net_override(self):
        buy = self.row(1, "BUY", 100, 10)
        other = {**self.row(2, "BUY", 200, 20), "environment": "testnet"}
        rows = [buy, other, self.row(3, "SELL", 110, 10, 10),
                {**self.row(4, "SELL", 220, 20, 20), "environment": "testnet"},
                self.row(5, "BUY", 50, 5),
                self.row(6, "SELL", 55, 5, 5, commission_status="actual",
                         commission_quote="0.03", net_pnl_usdt="4.93", pnl_status="actual")]
        result = self.frame(rows)
        self.assertAlmostEqual(result.iloc[2]["Net P&L (USDT)"], 9.79)
        self.assertAlmostEqual(result.iloc[3]["Net P&L (USDT)"], 19.58)
        self.assertAlmostEqual(result.iloc[5]["Net P&L (USDT)"], 4.93)
