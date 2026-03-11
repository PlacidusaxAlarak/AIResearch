import json
import os
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from airesearch.compatibility import resolve_config_path


def _load_yaml(path: str) -> dict:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


class TestOrchestratorCliCharacterization(unittest.TestCase):
    def test_package_entrypoint_exposes_main(self) -> None:
        from airesearch.__main__ import main as package_main

        self.assertTrue(callable(package_main))

    def test_python_m_airesearch_help_returns_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "airesearch", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertIn("--config", result.stdout)

    def test_pyproject_declares_console_script(self) -> None:
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        payload = tomllib.loads(pyproject)
        scripts = payload.get("project", {}).get("scripts", {})
        self.assertEqual("airesearch.__main__:main", scripts.get("airesearch"))

    def test_mcp_example_uses_module_entrypoints(self) -> None:
        payload = json.loads(Path("mcp.example.json").read_text(encoding="utf-8"))
        servers = payload["mcpServers"]
        expected_modules = {
            "arxiv": "airesearch.mcp.arxiv",
            "hf_papers": "airesearch.mcp.hf_papers",
            "scholarly": "airesearch.mcp.scholarly",
            "github": "airesearch.mcp.github",
            "obsidian": "airesearch.mcp.obsidian",
        }

        for server_name, module_name in expected_modules.items():
            server = servers[server_name]
            self.assertEqual("python", server["command"])
            self.assertEqual(["-m", module_name], server["args"])

    def test_config_priority_cli_over_env(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg_cli = Path(tmp) / "cli.yaml"
            cfg_env = Path(tmp) / "env.yaml"
            cfg_cli.write_text("state_dir: state\n", encoding="utf-8")
            cfg_env.write_text("state_dir: state\n", encoding="utf-8")

            old_env = os.environ.get("AIRESEARCH_CONFIG")
            os.environ["AIRESEARCH_CONFIG"] = str(cfg_env)
            try:
                selected = resolve_config_path(str(cfg_cli))
            finally:
                if old_env is None:
                    os.environ.pop("AIRESEARCH_CONFIG", None)
                else:
                    os.environ["AIRESEARCH_CONFIG"] = old_env

            self.assertEqual(cfg_cli.resolve(), selected)

    def test_config_priority_env_over_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg_env = Path(tmp) / "env.yaml"
            cfg_env.write_text("state_dir: state\n", encoding="utf-8")
            old_env = os.environ.get("AIRESEARCH_CONFIG")
            os.environ["AIRESEARCH_CONFIG"] = str(cfg_env)
            try:
                selected = resolve_config_path(None)
            finally:
                if old_env is None:
                    os.environ.pop("AIRESEARCH_CONFIG", None)
                else:
                    os.environ["AIRESEARCH_CONFIG"] = old_env

            self.assertEqual(cfg_env.resolve(), selected)


    def test_config_example_keywords_focus_on_core_directions(self) -> None:
        payload = _load_yaml("config.example.yaml")
        keywords = payload.get("keywords", [])

        self.assertLessEqual(len(keywords), 18)
        self.assertIn("rlvr", keywords)
        self.assertIn("reinforcement learning from human feedback", keywords)
        self.assertIn("direct preference optimization", keywords)
        self.assertIn("process reward model", keywords)
        self.assertIn("agentic reinforcement learning", keywords)
        self.assertIn("tool calling", keywords)
        self.assertIn("multi-turn agent", keywords)
        self.assertNotIn("multimodal rlhf", keywords)
        self.assertNotIn("vision-language alignment", keywords)
        self.assertNotIn("generative recommendation", keywords)
        self.assertNotIn("browser agent", keywords)

    def test_config_local_keywords_focus_on_core_directions(self) -> None:
        payload = _load_yaml("config.local.yaml")
        keywords = payload.get("keywords", [])
        topic_keywords = payload.get("topic_keywords", {})

        self.assertLessEqual(len(keywords), 18)
        self.assertIn("rlvr", keywords)
        self.assertIn("reinforcement learning from human feedback", keywords)
        self.assertIn("direct preference optimization", keywords)
        self.assertIn("process reward model", keywords)
        self.assertIn("agentic reinforcement learning", keywords)
        self.assertIn("tool calling", keywords)
        self.assertIn("multi-turn agent", keywords)
        self.assertNotIn("multimodal rlhf", keywords)
        self.assertNotIn("vision-language alignment", keywords)
        self.assertNotIn("generative recommendation", keywords)
        self.assertNotIn("browser agent", keywords)
        self.assertNotIn("domain_applications", topic_keywords)


if __name__ == "__main__":
    unittest.main()
