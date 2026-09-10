import json
import unittest
from decimal import Decimal
from unittest.mock import patch

import pandas as pd

import app


def make_klines(closes, low):
    return [
        [
            index,
            str(close),
            str(close + 1),
            str(low),
            str(close),
            "1",
            index,
            "1",
            1,
            "1",
            "1",
            "0",
        ]
        for index, close in enumerate(closes)
    ]


class FakeClient:
    def __init__(self, support_low=99.9):
        self.support_low = support_low

    def get_klines(self, symbol, interval, limit):
        if interval == "1h":
            return make_klines(list(range(80, 80 + limit)), 79)
        return make_klines([100 + index * 0.001 for index in range(limit)], self.support_low)


class FakeTickerClient:
    def get_ticker(self):
        return [
            {
                "symbol": "RLUSDUSDT", "quoteVolume": "130900000",
                "priceChangePercent": "0.01", "weightedAvgPrice": "1.0004",
                "highPrice": "1.0007", "lowPrice": "1.0001",
                "lastPrice": "1.0004",
            },
            {
                "symbol": "QUIETUSDT", "quoteVolume": "90000000",
                "priceChangePercent": "0.8", "weightedAvgPrice": "10",
                "highPrice": "10.05", "lowPrice": "9.95", "lastPrice": "10",
            },
            {
                "symbol": "ACTIVEUSDT", "quoteVolume": "90000000",
                "priceChangePercent": "3.2", "weightedAvgPrice": "10",
                "highPrice": "10.4", "lowPrice": "9.8", "lastPrice": "10.2",
            },
        ]


class FakePortfolioClient:
    def get_account(self):
        return {
            "balances": [
                {"asset": "USDT", "free": "100", "locked": "5"},
                {"asset": "SOL", "free": "2", "locked": "0"},
                {"asset": "ABC", "free": "10", "locked": "0"},
                {"asset": "UNKNOWN", "free": "3", "locked": "0"},
            ]
        }

    def get_all_tickers(self):
        return [
            {"symbol": "SOLUSDT", "price": "150"},
            {"symbol": "ABCBTC", "price": "0.001"},
            {"symbol": "BTCUSDT", "price": "60000"},
        ]


class StrategySignalTests(unittest.TestCase):
    def setUp(self):
        self.strategy = {
            "buy_rsi_recovery": app.DEFAULT_BUY_RSI_RECOVERY,
            "max_support_distance_pct": app.DEFAULT_MAX_SUPPORT_DISTANCE_PCT,
            "trend_interval": app.DEFAULT_TREND_INTERVAL,
            "trend_ema_period": app.DEFAULT_TREND_EMA_PERIOD,
            "min_net_reward_pct": app.DEFAULT_MIN_NET_REWARD_PCT,
            "min_net_profit_usdt": app.DEFAULT_MIN_NET_PROFIT_USDT,
            "estimated_round_trip_fee_pct": (
                app.DEFAULT_ESTIMATED_ROUND_TRIP_FEE_PCT
            ),
            "atr_sl_multiplier": app.DEFAULT_ATR_SL_MULTIPLIER,
            "risk_reward_ratio": app.DEFAULT_RISK_REWARD_RATIO,
            "sell_rsi_threshold": app.DEFAULT_SELL_RSI_THRESHOLD,
        }

    def test_minimum_net_exit_price_covers_fees_and_profit_floor(self):
        price = app.minimum_net_exit_price(
            Decimal("10"), Decimal("2.5"), Decimal("0.5"), Decimal("0.2")
        )
        fee_rate = Decimal("0.001")
        net_profit = (
            (price - Decimal("10")) * Decimal("2.5")
            - (price + Decimal("10")) * Decimal("2.5") * fee_rate
        )
        self.assertAlmostEqual(float(net_profit), 0.5, places=8)

    def test_automatic_buys_pause_only_in_active_weak_market(self):
        self.assertTrue(app.automatic_buys_paused({"regime": "ACTIVE / WEAK"}))
        self.assertFalse(app.automatic_buys_paused({"regime": "ACTIVE / POSITIVE"}))
        self.assertFalse(app.automatic_buys_paused({}))

    @patch("app.buy")
    def test_weak_market_override_preserves_entry_signal_and_manual_hold(self, buy):
        args = (
            None, "TESTUSDT", {}, {"entry": 10, "buy_signal": False}, {},
            Decimal("120"), Decimal("30"), 4,
        )
        weak = {"regime": "ACTIVE / WEAK"}
        self.assertEqual(
            app.decide_and_trade(*args, False, {}, weak), "WEAK MARKET PAUSE"
        )
        self.assertEqual(
            app.decide_and_trade(*args, False, {}, weak, ignore_weak_market=True),
            "WAITING TO BUY",
        )
        self.assertEqual(
            app.decide_and_trade(*args, True, {}, weak, ignore_weak_market=True),
            "ON HOLD",
        )
        buy.assert_not_called()

    def test_weak_market_override_disables_pause(self):
        self.assertFalse(app.automatic_buys_paused(
            {"regime": "ACTIVE / WEAK"}, ignore_weak_market=True
        ))

    @patch("app.sell", return_value=True)
    @patch("app.save_positions")
    def test_open_target_tracks_profit_floor_and_preserves_strategy(self, save, sell):
        position = {"entry": "10", "quantity": "2.5", "stop_loss": "9.95",
                    "take_profit": "10.3", "strategy_take_profit": "10.10"}
        analysis = {"entry": 10, "min_net_profit_usdt": 0,
                    "estimated_round_trip_fee_pct": 0.2, "sell_signal": False}
        def check():
            return app.decide_and_trade(None, "TESTUSDT", {}, analysis,
                                       {"TESTUSDT": position}, 100, 25, 4, False, {})
        self.assertEqual(check(), "MONITORING")
        self.assertEqual(Decimal(position["take_profit"]), Decimal("10.10"))
        analysis["min_net_profit_usdt"] = 1
        check()
        self.assertEqual(Decimal(position["take_profit"]),
                         app.minimum_net_exit_price(Decimal("10"), Decimal("2.5"), 1, .2))
        analysis["min_net_profit_usdt"] = 0
        analysis["entry"] = 10.11
        self.assertEqual(check(), "SELL FILLED")
        self.assertEqual(sell.call_args.args[-1], "take profit")

    @patch("app.sell")
    @patch("app.save_positions")
    def test_legacy_target_migrates_once_and_manual_target_is_untouched(self, save, sell):
        for manual in (False, True):
            position = {"entry": "10", "quantity": "2.5", "stop_loss": "9.95",
                        "take_profit": "10.3", "manual_take_profit": manual}
            analysis = {"entry": 10, "min_net_profit_usdt": 0,
                        "risk_reward_ratio": 2, "sell_signal": False}
            for ratio in (2, 3):
                analysis["risk_reward_ratio"] = ratio
                app.decide_and_trade(None, "TESTUSDT", {}, analysis,
                                     {"TESTUSDT": position}, 100, 25, 4, False, {})
                self.assertEqual(Decimal(position["take_profit"]),
                                 Decimal("10.3" if manual else "10.10"))
            self.assertEqual("strategy_take_profit" in position, not manual)
        sell.assert_not_called()

    @patch("app.calculate_atr")
    @patch("app.calculate_rsi")
    def test_buy_requires_all_confirmations(self, calculate_rsi, calculate_atr):
        calculate_rsi.side_effect = lambda data: pd.Series(
            [40.0] * (len(data) - 2) + [34.0, 36.0]
        )
        calculate_atr.side_effect = lambda data: pd.Series([0.5] * len(data))

        analysis = app.analyze_market(
            FakeClient(), "TESTUSDT", "15m", self.strategy
        )

        self.assertTrue(analysis["rsi_recovered"])
        self.assertTrue(analysis["near_support"])
        self.assertTrue(analysis["trend_ok"])
        self.assertTrue(analysis["reward_ok"])
        self.assertTrue(analysis["momentum_ok"])
        self.assertTrue(analysis["buy_signal"])
        for name in (
            "rsi_recovered", "near_support", "trend_ok", "reward_ok",
            "buy_signal", "sell_signal",
        ):
            self.assertIs(type(analysis[name]), bool)
        json.dumps(analysis)

    @patch("app.calculate_atr")
    @patch("app.calculate_rsi")
    def test_rsi_recovery_window_boundaries(self, calculate_rsi, calculate_atr):
        calculate_atr.side_effect = lambda data: pd.Series([0.5] * len(data))
        cases = [
            (1, [32, 36, 38, 40], False),
            (3, [32, 36, 38, 40], True),
            (3, [32, 36, 38, 40, 42], False),
            (3, [32, 36, 40, 38], False),
            (3, [32, 36, 38, 38], False),
            (3, [32, 36, 33, 34], False),
            (3, [32, 36, 33, 35], False),
            (1, [35, 36], True),
        ]
        for window, values, expected in cases:
            with self.subTest(window=window, values=values):
                calculate_rsi.side_effect = lambda data: pd.Series(
                    [40.0] * (len(data) - len(values)) + values
                )
                strategy = {**self.strategy, "rsi_recovery_window": window}
                analysis = app.analyze_market(FakeClient(), "TESTUSDT", "15m", strategy)
                self.assertEqual(analysis["rsi_recovered"], expected)
                self.assertEqual(analysis["buy_signal"], expected)

    @patch("app.calculate_atr")
    @patch("app.calculate_rsi")
    def test_one_failed_confirmation_blocks_buy(self, calculate_rsi, calculate_atr):
        calculate_rsi.side_effect = lambda data: pd.Series(
            [40.0] * (len(data) - 2) + [34.0, 36.0]
        )
        calculate_atr.side_effect = lambda data: pd.Series([0.5] * len(data))

        analysis = app.analyze_market(
            FakeClient(support_low=95), "TESTUSDT", "15m", self.strategy
        )

        self.assertFalse(analysis["near_support"])
        self.assertFalse(analysis["buy_signal"])

    def test_watchlist_excludes_stablecoins_and_low_range_pairs(self):
        suggestions, overview = app.get_market_suggestions(
            FakeTickerClient(), 0.20
        )

        self.assertEqual([item["symbol"] for item in suggestions], ["ACTIVEUSDT"])
        self.assertIn("after estimated costs", suggestions[0]["analysis"])
        self.assertEqual(overview["sample_size"], 2)

    def test_market_overview_identifies_quiet_weak_breadth(self):
        overview = app.classify_market_overview(
            [
                {"change_pct": -2.0, "range_pct": 1.0},
                {"change_pct": -1.8, "range_pct": 1.2},
                {"change_pct": -1.6, "range_pct": 0.9},
                {"change_pct": 0.1, "range_pct": 1.1},
            ]
        )

        self.assertEqual(overview["regime"], "QUIET / WEAK")
        self.assertEqual(overview["active_pct"], 0.0)

    def test_spot_portfolio_includes_free_locked_and_bridged_assets(self):
        available, total, unpriced = app.get_spot_portfolio_value(
            FakePortfolioClient()
        )

        self.assertEqual(available, Decimal("100"))
        self.assertEqual(total, Decimal("1005.000"))
        self.assertEqual(unpriced, ["UNKNOWN"])


if __name__ == "__main__":
    unittest.main()
