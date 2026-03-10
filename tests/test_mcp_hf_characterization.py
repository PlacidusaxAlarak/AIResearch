import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from airesearch.mcp import hf_papers as hf_papers_mcp


class _Resp:
    def __init__(self, payload) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class TestHfPapersMcpCharacterization(unittest.TestCase):
    def test_build_result_fills_core_fields(self) -> None:
        item = {
            "paper": {
                "title": "A Title",
                "summary": "A Summary",
                "authors": [{"name": "Alice"}],
                "paperId": "2602.10177",
            }
        }
        out = hf_papers_mcp._build_result(item, terms=["title"])
        self.assertIsNotNone(out)
        assert out is not None
        for key in ("id", "title", "abstract", "authors", "url", "pdf_url", "published"):
            self.assertIn(key, out)
        self.assertEqual("2602.10177", out["id"])
        self.assertEqual(["Alice"], out["authors"])

    def test_papers_search_obeys_limit_and_filter(self) -> None:
        items = [
            {"title": "chain-of-thought X", "summary": "", "id": "1"},
            {"title": "chain-of-thought Y", "summary": "", "id": "2"},
            {"title": "unrelated", "summary": "", "id": "3"},
        ]
        with patch.object(hf_papers_mcp, "_fetch_day", return_value=items):
            out = hf_papers_mcp.papers_search("chain-of-thought", limit=2, days_back=2)
        self.assertEqual(2, len(out))
        self.assertEqual(["1", "2"], [x["id"] for x in out])

    def test_papers_trending_filters_keywords(self) -> None:
        items = [
            {"title": "tool use", "summary": "", "id": "a"},
            {"title": "other", "summary": "", "id": "b"},
        ]
        with patch.object(hf_papers_mcp, "_fetch_endpoint", return_value=items):
            out = hf_papers_mcp.papers_trending("tool", limit=10)
        self.assertEqual(["a"], [x["id"] for x in out])

    def test_fetch_endpoint_400_uses_max_date_fallback(self) -> None:
        err_body = b'{"error":"max date is \\"2026-02-01T00:00:00Z\\""}'
        first = HTTPError("http://x", 400, "bad", {}, io.BytesIO(err_body))
        second = _Resp([{"id": "ok", "title": "t", "summary": "s"}])
        with patch("urllib.request.urlopen", side_effect=[first, second]):
            out = hf_papers_mcp._fetch_endpoint({"date": "2026-02-10"}, date_str="2026-02-10")
        self.assertEqual(1, len(out))
        self.assertEqual("ok", out[0]["id"])


if __name__ == "__main__":
    unittest.main()
