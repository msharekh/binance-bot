import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

import app


class LiveTakeProfitTests(unittest.TestCase):
    def setUp(self):
        self.positions = {"TESTUSDT": {"take_profit": "105", "stop_loss": "95"}}
        self.rules = {"TESTUSDT": {}}

    def check(self, prices):
        app.check_live_take_profits(Mock(), self.positions, self.rules, prices)

    @patch.object(app, "TRADING_ENABLED", True)
    @patch.object(app, "sell")
    def test_target_touch_and_cross_sell_at_live_price(self, sell):
        for price in ("105", "106"):
            with self.subTest(price=price):
                sell.reset_mock()
                self.check({"TESTUSDT": Decimal(price)})
                sell.assert_called_once()
                self.assertEqual(sell.call_args.args[4], {"entry": Decimal(price)})
                self.assertEqual(sell.call_args.args[6], "take profit")

    @patch.object(app, "TRADING_ENABLED", True)
    @patch.object(app, "sell")
    def test_no_live_stop_loss_or_stale_price_sale(self, sell):
        for prices in (None, {}, {"TESTUSDT": "94"}, {"TESTUSDT": "104"},
                       {"TESTUSDT": "NaN"}):
            self.check(prices)
        sell.assert_not_called()

    @patch.object(app, "TRADING_ENABLED", False)
    @patch.object(app, "sell")
    def test_analysis_only_never_sells(self, sell):
        self.check({"TESTUSDT": "106"})
        sell.assert_not_called()

    @patch.object(app, "TRADING_ENABLED", True)
    @patch.object(app, "process_buy_requests")
    @patch.object(app, "process_sell_requests")
    @patch.object(app.time, "sleep")
    @patch.object(app, "refresh_live_prices", return_value={"TESTUSDT": "105"})
    @patch.object(app, "sell")
    def test_wait_loop_checks_tp_and_removes_sold_position(
        self, sell, refresh, sleep, manual_sell, manual_buy
    ):
        sell.side_effect = lambda *args: self.positions.pop(args[1])
        clock = [0.0]
        sleep.side_effect = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        with patch.object(app.time, "monotonic", side_effect=lambda: clock[0]):
            app.wait_for_next_cycle(
                Mock(), self.positions, self.rules, ["TESTUSDT"],
                {"poll_seconds": 10, "live_price_refresh_seconds": 2},
            )
        sell.assert_called_once()
        self.assertEqual(refresh.call_count, 4)
        self.assertEqual(self.positions, {})

    @patch.object(app, "TRADING_ENABLED", False)
    def test_five_second_refresh_runs_at_five_and_ten_seconds(self):
        clock = [0.0]
        refresh_times = []
        def sleep(seconds):
            clock[0] += seconds
        with patch.object(app.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(app.time, "sleep", side_effect=sleep), \
             patch.object(app, "refresh_live_prices", side_effect=lambda *args: refresh_times.append(clock[0])):
            app.wait_for_next_cycle(
                Mock(), {}, {}, [],
                {"poll_seconds": 15, "live_price_refresh_seconds": 5},
            )
        self.assertEqual(refresh_times, [5, 10])
        self.assertEqual(clock[0], 15)


if __name__ == "__main__":
    unittest.main()
