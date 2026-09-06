import json
import unittest

from entry_conditions import capture_entry_conditions, entry_conditions_html


class EntryConditionsTests(unittest.TestCase):
    def test_current_analysis_overrides_green_entry(self):
        position = {"entry_conditions": {"momentum_ok": True}}
        markup = entry_conditions_html(position, {"momentum_ok": False})
        self.assertIn("EMA 9 &gt; EMA 21: Not met in latest analysis", markup)
        self.assertIn("Current conditions", markup)
        self.assertTrue(position["entry_conditions"]["momentum_ok"])

    def test_missing_current_checks_do_not_show_saved_green(self):
        markup = entry_conditions_html(
            {"entry_conditions": {"momentum_ok": True}}, {}
        )
        self.assertEqual(markup.count('background:#94a3b8'), 6)

    def test_snapshot_survives_changes_and_json_round_trip(self):
        analysis = {"momentum_ok": True, "trend_ok": False}
        snapshot = capture_entry_conditions(analysis)
        analysis["momentum_ok"] = False
        stored = json.loads(json.dumps({"entry_conditions": snapshot}))
        markup = entry_conditions_html(stored)
        self.assertIn("EMA 9 &gt; EMA 21: Met at entry", markup)
        self.assertIn("Higher-timeframe EMA trend: Not met at entry", markup)
        self.assertIn("RSI recovery: Not recorded at entry", markup)

    def test_legacy_position_has_six_unknown_checks(self):
        markup = entry_conditions_html({})
        self.assertEqual(markup.count('background:#94a3b8'), 6)
        self.assertNotIn('background:#22c55e', markup)
