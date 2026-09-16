import unittest
import ast
from pathlib import Path
from datetime import datetime
from bisect import bisect_right
import pandas as pd
from decimal import Decimal as D
from unittest.mock import Mock, patch

import app
from commission_accounting import order_commissions, entry_cost, realized_profit


RULES = {"base_asset": "ABC", "quote_asset": "USDT", "quote_precision": 2,
         "step_size": D("0.001"), "min_quantity": D("0.001"), "min_notional": D("1")}


def order(side="BUY", asset="USDT", fee="0.1", qty="10", value="100"):
    return {"orderId": 123, "executedQty": qty, "cummulativeQuoteQty": value,
            "fills": [{"qty": qty, "price": str(D(value) / D(qty)),
                       "commission": fee, "commissionAsset": asset}]}


class CommissionTests(unittest.TestCase):
    def test_dashboard_prefers_recorded_net_and_marks_unknown(self):
        tree = ast.parse(Path("dashboard.py").read_text(encoding="utf-8"))
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name in ("transaction_frame", "transaction_result")]
        scope = {"pd": pd, "datetime": datetime, "bisect_right": bisect_right,
                 "read_market_overview_history": lambda: [],
                 "read_json": lambda *args: {}, "CONFIG_FILE": None}
        exec(compile(ast.Module(body=selected, type_ignores=[]), "dashboard.py", "exec"), scope)
        rows = [dict(side="SELL", symbol="ABCUSDT", recorded_at=1, quote_amount="101",
                     estimated_pnl_usdt="1", net_pnl_usdt="0.799",
                     commission_quote="0.101", commission_status="actual", pnl_status="actual"),
                dict(side="SELL", symbol="ABCUSDT", recorded_at=2, quote_amount="101",
                     estimated_pnl_usdt="1", net_pnl_usdt=None,
                     commission_quote="0.101", commission_status="actual", pnl_status="missing"),
                dict(side="SELL", symbol="ABCUSDT", recorded_at=3, quote_amount="101",
                     estimated_pnl_usdt="1")]
        frame = scope["transaction_frame"](rows)
        self.assertAlmostEqual(frame.iloc[0]["Net P&L (USDT)"], .799)
        self.assertEqual(scope["transaction_result"](frame.iloc[1]), "UNKNOWN")
        self.assertEqual(frame.iloc[2]["P&L basis"], "legacy fee estimate")

    def test_quote_fees_both_legs(self):
        fees = order_commissions(Mock(), order(), RULES)
        cost = entry_cost(D(100), fees)
        self.assertEqual(D(cost), D("100.1"))
        exit_fees = order_commissions(Mock(), order(value="101", fee="0.101"), RULES)
        result, remaining = realized_profit({"quantity": "10", "cost_basis_quote": cost}, D(10), D(101), exit_fees)
        self.assertEqual(D(result["net_pnl_usdt"]), D("0.799"))
        self.assertEqual(remaining, 0)

    def test_base_fee_reduces_inventory_without_double_charge(self):
        fees = order_commissions(Mock(), order(asset="ABC", fee="0.01"), RULES)
        self.assertEqual(D(entry_cost(D(100), fees)), D(100))
        exit_fees = order_commissions(Mock(), order(qty="9.99", value="100.899", fee="0.100899"), RULES)
        result, _ = realized_profit({"quantity": "9.99", "cost_basis_quote": "100"}, D("9.99"), D("100.899"), exit_fees)
        self.assertEqual(D(result["net_pnl_usdt"]), D("0.798101"))

    def test_bnb_conversion_and_failure(self):
        client = Mock()
        client.get_symbol_ticker.return_value = {"price": "600"}
        fees = order_commissions(client, order(asset="BNB", fee="0.0001"), RULES)
        self.assertEqual(D(fees["commission_quote"]), D("0.06"))
        self.assertEqual(fees["commission_status"], "converted_estimate")
        client.get_symbol_ticker.side_effect = RuntimeError("offline")
        fees = order_commissions(client, order(asset="BNB", fee="0.0001"), RULES)
        self.assertIsNone(fees["commission_quote"])
        self.assertEqual(fees["commissions"], {"BNB": "0.0001"})

    def test_missing_and_zero_fees_are_distinct(self):
        missing = order(); missing.pop("fills")
        self.assertIsNone(order_commissions(Mock(), missing, RULES)["commission_quote"])
        self.assertEqual(order_commissions(Mock(), order(fee="0"), RULES)["commission_quote"], "0")

    def test_multiple_fills_and_partial_exit(self):
        data = order()
        data["fills"] = [dict(data["fills"][0], qty="5", commission="0.05")] * 2
        fees = order_commissions(Mock(), data, RULES)
        self.assertEqual(D(fees["commission_quote"]), D("0.10"))
        cost = entry_cost(D(100), fees, {"cost_basis_quote": "100.1"})
        result, remaining = realized_profit({"quantity": "20", "cost_basis_quote": cost}, D(10), D(101), fees)
        self.assertEqual(D(result["net_pnl_usdt"]), D("0.8"))
        self.assertEqual(remaining, 10)
        result, _ = realized_profit({"quantity": "20"}, D(10), D(101), fees)
        self.assertIsNone(result["net_pnl_usdt"])

    @patch("app.print_status")
    @patch("app.save_positions")
    @patch("app.record_transaction")
    @patch("app.get_free_balance", return_value=D(1000))
    def test_buy_sell_records_actual_net(self, balance, record, save, status):
        client = Mock()
        client.create_order.side_effect = [order(asset="ABC", fee="0.01"),
                                          order(qty="9.99", value="100.899", fee="0.100899")]
        positions = {}
        analysis = {"entry": 10, "tp": 11, "stop_distance": 1, "signal_candle_close_time": 1}
        position = app.buy(client, "ABCUSDT", RULES, analysis, positions, D(200), D(100), 6)
        self.assertEqual(D(position["quantity"]), D("9.99"))
        app.sell(client, "ABCUSDT", RULES, position, analysis, positions, "take profit")
        self.assertEqual(D(record.call_args.args[0]["net_pnl_usdt"]), D("0.798101"))
        self.assertEqual(positions, {})
