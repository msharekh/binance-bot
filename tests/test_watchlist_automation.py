import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from watchlist_automation import apply_watchlist_automation


class WatchlistAutomationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.json"
        self.config = {
            "target_symbols": ["OLDUSDT", "KEEPUSDT"],
            "max_total_exposure_usdt": "120",
            "trade_amount_usdt": "30",
        }
        self.suggestions = [{"symbol": "KEEPUSDT"}, {"symbol": "NEWUSDT"}]

    def apply(self, **settings):
        self.config.update(settings)
        self.path.write_text(json.dumps(self.config), encoding="utf-8")
        changed = apply_watchlist_automation(self.path, self.suggestions)
        return changed, json.loads(self.path.read_text(encoding="utf-8"))

    def test_default_off_does_not_write(self):
        changed, result = self.apply()
        self.assertFalse(changed)
        self.assertEqual(result, self.config)

    def test_add_only_and_repeated_cycles(self):
        changed, result = self.apply(auto_add_candidates=True)
        self.assertTrue(changed)
        self.assertEqual(result["target_symbols"], ["OLDUSDT", "KEEPUSDT", "NEWUSDT"])
        self.assertEqual(result["trade_amount_usdt"], "30")
        self.assertFalse(apply_watchlist_automation(self.path, self.suggestions))

    def test_remove_only(self):
        _, result = self.apply(auto_remove_avoided=True)
        self.assertEqual(result["target_symbols"], ["KEEPUSDT"])

    def test_both_follow_changing_screen(self):
        _, result = self.apply(auto_add_candidates=True, auto_remove_avoided=True)
        self.assertEqual(result["target_symbols"], ["KEEPUSDT", "NEWUSDT"])
        apply_watchlist_automation(self.path, [{"symbol": "OTHERUSDT"}])
        self.assertEqual(json.loads(self.path.read_text())["target_symbols"], ["OTHERUSDT"])

    def test_turning_off_stops_updates(self):
        self.apply(auto_add_candidates=True, auto_remove_avoided=True)
        self.config = json.loads(self.path.read_text())
        self.suggestions = [{"symbol": "OTHERUSDT"}]
        changed, result = self.apply(auto_add_candidates=False, auto_remove_avoided=False)
        self.assertFalse(changed)
        self.assertEqual(result["target_symbols"], ["KEEPUSDT", "NEWUSDT"])

    def test_empty_screen_does_not_remove_targets(self):
        self.suggestions = []
        changed, result = self.apply(auto_remove_avoided=True)
        self.assertFalse(changed)
        self.assertEqual(result["target_symbols"], self.config["target_symbols"])

    def test_removing_last_target_does_not_restore_default_targets(self):
        self.suggestions = [{"symbol": "OTHERUSDT"}]
        _, result = self.apply(auto_remove_avoided=True)
        self.assertEqual(result["target_symbols"], [])
        with patch.object(app, "CONFIG_FILE", self.path):
            self.assertEqual(app.load_runtime_config()["target_symbols"], [])


if __name__ == "__main__":
    unittest.main()
