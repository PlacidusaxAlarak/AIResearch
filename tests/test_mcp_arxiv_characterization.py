import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from airesearch.mcp import arxiv as arxiv_mcp


class _Resp:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class TestArxivMcpCharacterization(unittest.TestCase):
    def test_build_query_formats_terms(self) -> None:
        query = arxiv_mcp._build_query("chain-of-thought OR cs.CL OR tree of thoughts")
        self.assertIn("all:chain-of-thought", query)
        self.assertIn("cs.CL", query)
        self.assertIn('all:"tree of thoughts"', query)

    def test_search_returns_expected_fields(self) -> None:
        atom = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2602.10177v1</id>
    <title> Test Title </title>
    <summary> Test Summary </summary>
    <published>2026-02-01T12:00:00Z</published>
    <author><name>Alice</name></author>
    <link href="http://arxiv.org/abs/2602.10177v1"/>
    <link title="pdf" rel="related" type="application/pdf" href="http://arxiv.org/pdf/2602.10177v1"/>
  </entry>
</feed>
"""
        with patch("urllib.request.urlopen", return_value=_Resp(atom)):
            items = arxiv_mcp.search("chain-of-thought", max_results=1)
        self.assertEqual(1, len(items))
        item = items[0]
        for key in ("id", "title", "summary", "authors", "url", "pdf_url", "published"):
            self.assertIn(key, item)
        self.assertEqual("2602.10177v1", item["id"])

    def test_source_fetch_contract(self) -> None:
        fake = {
            "ok": True,
            "archive_path": "a.tar.gz",
            "output_dir": "out",
            "tex_path": "main.tex",
            "tex_files": ["main.tex"],
        }
        with patch.object(arxiv_mcp, "_download_source", return_value=fake) as mocked:
            out = arxiv_mcp.source_fetch("2602.10177", output_dir="output/latex")
        mocked.assert_called_once()
        self.assertEqual(fake, out)

    def test_retry_branch_on_transient_http_error(self) -> None:
        http_err = HTTPError("http://x", 500, "err", {}, io.BytesIO(b""))
        with (
            patch("urllib.request.urlopen", side_effect=[http_err, _Resp(b"ok")]),
            patch("airesearch.mcp.arxiv.time.sleep"),
        ):
            data = arxiv_mcp._read_with_retries(
                arxiv_mcp.urllib.request.Request("http://x"),
                timeout_sec=10,
            )
        self.assertEqual(b"ok", data)


if __name__ == "__main__":
    unittest.main()
