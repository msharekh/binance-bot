import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app


class CooldownSaveTests(unittest.TestCase):
    def test_temporary_lock_retries_and_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "entry_cooldowns.json"
            target.write_text('{"old": true}', encoding="utf-8")
            replace = Path.replace
            attempts = []

            def locked_replace(source, destination):
                attempts.append(source)
                if len(attempts) < 3:
                    raise PermissionError("file locked")
                return replace(source, destination)

            with patch.object(app, "ENTRY_COOLDOWN_FILE", target), \
                 patch.object(Path, "replace", locked_replace), \
                 patch.object(app.time, "sleep") as sleep:
                app.save_entry_cooldowns({"TESTUSDT": 123})
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(json.loads(target.read_text())["last_entry_candle"],
                             {"TESTUSDT": 123})

    def test_persistent_lock_preserves_previous_file_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "entry_cooldowns.json"
            original = '{"old": true}'
            target.write_text(original, encoding="utf-8")
            with patch.object(app, "ENTRY_COOLDOWN_FILE", target), \
                 patch.object(Path, "replace", side_effect=PermissionError("locked")), \
                 patch.object(app.time, "sleep") as sleep:
                with self.assertRaisesRegex(PermissionError, "previous cooldown file was preserved"):
                    app.save_entry_cooldowns({"TESTUSDT": 123})
            self.assertEqual(sleep.call_count, 9)
            self.assertEqual(target.read_text(), original)
