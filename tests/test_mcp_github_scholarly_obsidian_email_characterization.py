import io
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError

from airesearch.mcp import email as email_mcp
from airesearch.mcp import github as github_mcp
from airesearch.mcp import obsidian as obsidian_mcp
from airesearch.mcp import scholarly as scholarly_mcp
from airesearch.compatibility import resolve_mcp_config_path


class _Resp:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class TestMcpGithubScholarlyObsidianEmailCharacterization(unittest.TestCase):
    def test_github_repo_tree_depth_filter(self) -> None:
        payload = {
            "tree": [
                {"type": "blob", "path": "a.py"},
                {"type": "blob", "path": "dir/b.py"},
                {"type": "tree", "path": "dir"},
            ]
        }
        with patch.object(github_mcp, "_get_tree", return_value=payload):
            paths = github_mcp.repo_tree("o", "r", ref="main", max_depth=1)
        self.assertEqual(["a.py"], paths)

    def test_scholarly_lookup_404_returns_not_found_shape(self) -> None:
        err = HTTPError("http://x", 404, "missing", {}, io.BytesIO(b"{}"))
        with patch("urllib.request.urlopen", side_effect=err):
            out = scholarly_mcp.paper_lookup("2602.10177v2")
        self.assertEqual(0, out.get("citationCount"))
        self.assertTrue(out.get("notFound"))

    def test_obsidian_write_note_stays_inside_vault(self) -> None:
        vault = Path("tests") / "_tmp_obsidian" / "vault"
        vault.mkdir(parents=True, exist_ok=True)
        with patch.object(obsidian_mcp, "_get_vault", return_value=vault.resolve()):
            out = obsidian_mcp.write_note("papers/test.md", "hello")
        target = Path(out["path"])
        self.assertTrue(target.exists())
        self.assertEqual("hello", target.read_text(encoding="utf-8"))

    def test_email_recipient_parser_from_csv(self) -> None:
        out = email_mcp._get_recipients("a@x.com; b@y.com, c@z.com")
        self.assertEqual(["a@x.com", "b@y.com", "c@z.com"], out)

    def test_mcp_config_priority_env(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "mcp.test.json"
            cfg.write_text("{}", encoding="utf-8")
            old_env = os.environ.get("AIRESEARCH_MCP_CONFIG")
            os.environ["AIRESEARCH_MCP_CONFIG"] = str(cfg)
            try:
                selected = resolve_mcp_config_path()
            finally:
                if old_env is None:
                    os.environ.pop("AIRESEARCH_MCP_CONFIG", None)
                else:
                    os.environ["AIRESEARCH_MCP_CONFIG"] = old_env
            self.assertEqual(cfg.resolve(), selected)


if __name__ == "__main__":
    unittest.main()
