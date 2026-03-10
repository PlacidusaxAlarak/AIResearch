import json
import unittest
from unittest.mock import Mock, patch

from airesearch.cli import orchestrator as orch_impl


class TestOrchestratorStateCharacterization(unittest.TestCase):
    def test_last_run_roundtrip_dict_payload(self) -> None:
        path = Mock()
        path.parent = Mock()
        path.write_text = Mock()
        path.exists = Mock(return_value=True)
        path.read_text = Mock(return_value=json.dumps({"date": "2026-02-14"}))

        orch_impl.save_last_run(path, "2026-02-14")
        path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        written_payload = json.loads(path.write_text.call_args.args[0])
        self.assertEqual({"date": "2026-02-14"}, written_payload)
        self.assertEqual("2026-02-14", orch_impl.load_last_run(path))

    def test_load_last_run_supports_legacy_string_format(self) -> None:
        path = Mock()
        path.exists = Mock(return_value=True)
        path.read_text = Mock(return_value=json.dumps("2026-02-13"))
        self.assertEqual("2026-02-13", orch_impl.load_last_run(path))

    def test_save_seen_is_noop(self) -> None:
        with patch.object(orch_impl, "SEEN_CACHE_PATH", Mock()) as seen_path:
            orch_impl.save_seen({"b", "a"})
            self.assertFalse(seen_path.parent.mkdir.called)
            self.assertFalse(seen_path.write_text.called)

    def test_load_seen_always_returns_empty_set(self) -> None:
        self.assertEqual(set(), orch_impl.load_seen())

    def test_apply_config_seen_cache_path_warns_deprecated(self) -> None:
        with patch.object(orch_impl, "_log") as log_mock:
            orch_impl.apply_config({"seen_cache_path": "state/seen_papers.json"})

        warn_messages = [
            call.args[1]
            for call in log_mock.call_args_list
            if len(call.args) >= 2 and call.args[0] == "WARN"
        ]
        self.assertTrue(
            any("seen_cache_path is deprecated and ignored" in msg for msg in warn_messages)
        )


if __name__ == "__main__":
    unittest.main()
