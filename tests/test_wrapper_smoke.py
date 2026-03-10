import unittest

from airesearch.cli import orchestrator
from airesearch.core import codex_cli, latex_reader, smtp_send
from airesearch.mcp import arxiv as arxiv_mcp
from airesearch.mcp import email as email_mcp
from airesearch.mcp import fetch as fetch_mcp
from airesearch.mcp import github as github_mcp
from airesearch.mcp import hf_papers as hf_papers_mcp
from airesearch.mcp import magic_pdf as magic_pdf_mcp
from airesearch.mcp import obsidian as obsidian_mcp
from airesearch.mcp import scholarly as scholarly_mcp


class TestPublicModuleSmoke(unittest.TestCase):
    def test_package_imports(self) -> None:
        from airesearch.__main__ import main as package_main

        self.assertTrue(callable(package_main))
        self.assertTrue(hasattr(orchestrator, "main"))
        self.assertTrue(hasattr(arxiv_mcp, "search"))
        self.assertTrue(hasattr(hf_papers_mcp, "papers_search"))
        self.assertTrue(hasattr(github_mcp, "repo_info"))
        self.assertTrue(hasattr(email_mcp, "send_email"))
        self.assertTrue(hasattr(fetch_mcp, "download"))
        self.assertTrue(hasattr(scholarly_mcp, "paper_lookup"))
        self.assertTrue(hasattr(obsidian_mcp, "write_note"))
        self.assertTrue(hasattr(magic_pdf_mcp, "magic_pdf_parse"))
        self.assertTrue(hasattr(codex_cli, "run_json"))
        self.assertTrue(hasattr(latex_reader, "read_latex_tree"))
        self.assertTrue(hasattr(smtp_send, "send_smtp_email"))


if __name__ == "__main__":
    unittest.main()
