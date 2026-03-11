from __future__ import annotations

import atexit
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, TextIO, Tuple
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import anyio
import yaml

from ..compatibility import repo_root, resolve_config_path
from ..core import codex_cli, latex_reader, mineru_pdf
from ..mcp import arxiv as arxiv_mcp
from ..mcp import email as email_mcp
from ..mcp import github as github_mcp
from ..mcp import hf_papers as hf_papers_mcp
from ..mcp import obsidian as obsidian_mcp
from ..mcp import scholarly as scholarly_mcp

# ------------------
# Config
# ------------------
REPO_ROOT = repo_root()
BASE_DIR = REPO_ROOT
CONFIG_PATH: Optional[Path] = None
CONFIG_BASE_DIR = REPO_ROOT

KEYWORDS = [
    "test-time scaling",
    "test-time compute",
    "inference-time scaling laws",
    "compute-optimal scaling",
    "process reward model",
    "outcome reward model",
    "rlvr",
    "grpo",
    "online preference learning",
    "reward hacking",
    "scalable oversight",
]
TOPIC_KEYWORDS = {
    "inference_compute_scaling": [
        "test-time scaling",
        "test-time compute",
        "inference-time scaling laws",
        "compute-optimal scaling",
        "hidden chain-of-thought",
        "system 1",
        "system 2",
        "search-based decoding",
        "mcts",
        "beam search",
        "best-of-n",
    ],
    "fine_grained_reward_modeling": [
        "process reward model",
        "prm",
        "outcome reward model",
        "orm",
        "reasoning-driven prm",
        "r-prm",
        "rlvr",
        "tool-call reward model",
        "credit assignment",
    ],
    "self_evolution_synthetic_loops": [
        "self-play rl",
        "serl",
        "multi-role self-play",
        "self-play theorem prover",
        "label-free optimization",
        "automated curriculum learning",
        "consensus filtering",
    ],
    "advanced_optimization_alignment": [
        "group relative policy optimization",
        "grpo",
        "direct preference optimization",
        "dpo",
        "uni-dpo",
        "inspo",
        "online preference learning",
        "evolution strategies",
        "reference-free alignment",
    ],
    "limitations_oversight": [
        "reward hacking",
        "reward tampering",
        "scalable oversight",
        "nested scalable oversight",
        "diversity collapse",
        "weak-to-strong generalization",
        "post-training",
        "post training",
        "rl agent",
        "tool use",
    ],
}
TOPIC_BOOST = {
    "inference_compute_scaling": 2.6,
    "fine_grained_reward_modeling": 2.8,
    "self_evolution_synthetic_loops": 2.4,
    "advanced_optimization_alignment": 2.3,
    "limitations_oversight": 1.9,
    "generic_penalty": -1.2,
}
GENERIC_RLHF_TERMS = [
    "rlhf",
    "dpo",
    "rlaif",
    "ppo",
    "grpo",
    "ipo",
    "orpo",
    "sft",
    "reward modeling",
]

# Deprecated compatibility shims: base filter no longer uses age/citation velocity.
NEW_PAPER_DAYS = 90
CITATION_VELOCITY_THRESHOLD = 2.0  # citations per month

DAYS_BACK = 7
ARXIV_QUERY_MAX_TERMS = 8
ARXIV_MAX_RESULTS_PER_QUERY = 50
HF_TRENDING_LIMIT = 50
HF_DATE_FIELD = "submitted_on_daily"

STAGE1_PREFILTER_ENABLED = True
STAGE1_TOP_N = 40
STAGE1_MIN_SCORE = 0.8
STAGE1_FALLBACK_TOP_K = 12

CODEX_CANDIDATE_SCORE_THRESHOLD = 3.6
CANDIDATE_RELEVANCE_MIN = 3.2
CANDIDATE_EVIDENCE_MIN = 2.8
CANDIDATE_SCORE_WEIGHTS = {
    "relevance_score": 1.4,
    "novelty_score": 1.1,
    "evidence_score": 1.3,
    "reproducibility_score": 1.0,
    "clarity_score": 0.7,
    "impact_score": 0.9,
}

WHITELIST_BONUS = 0.5
FRONTIER_YEAR_START = 2024
FRONTIER_YEAR_END = 2026

WHITELIST_PATH = BASE_DIR / "configs" / "whitelist_authors.yaml"
SUPER_WHITELIST_PATH = BASE_DIR / "configs" / "super_whitelist.yaml"
SUPER_WHITELIST_ENABLED_MAIN = True
SUPER_WHITELIST_TEXT_LIMIT = 8000
SUPER_WHITELIST_FORCE_NOTIFY = True
SUPER_WHITELIST_MIN_ALIAS_LEN = 4

SEEN_CACHE_PATH = BASE_DIR / "state" / "seen_papers.json"
OUTPUT_ROOT = BASE_DIR / "output"
OBSIDIAN_NOTE_DIR = "papers"
STATE_DIR = BASE_DIR / "state"
LAST_RUN_PATH = STATE_DIR / "last_run.json"
CST_TZ = timezone(timedelta(hours=8))

EMAIL_RECIPIENTS: List[str] = []
EMAIL_SUBJECT_PREFIX = "[AIResearch] "
EMAIL_ACCOUNT_NAME = "qq"

CODEX_PROMPT_PAPER_ANALYSIS_PATH = BASE_DIR / "prompts" / "codex_paper_analysis.txt"
CODEX_PROMPT_CANDIDATE_PATH = BASE_DIR / "prompts" / "codex_candidate_score.txt"

MINERU_POLL_INTERVAL_SEC = 5
MINERU_PER_RUN_TIMEOUT_SEC = 600
MINERU_MAX_ATTEMPTS = 3
MINERU_BACKOFF_BASE_SEC = 2.0

CODEX_TIMEOUT_SEC = 600
CODEX_CHUNK_CHARS = 12000
CODEX_CHUNK_OVERLAP = 800
CODEX_SKIP_GIT_REPO_CHECK = False
CODEX_USE_SEARCH = False
CODEX_MAX_CONCURRENCY = 8
PAPER_EVAL_CONCURRENCY = 8

GITHUB_SCAN_MAX = 3
OBSIDIAN_VAULT: Optional[str] = None

ACTIVE_DATE_WINDOW: Optional["DateWindow"] = None
_CODEX_SEMAPHORE: Optional[anyio.Semaphore] = None

CANDIDATE_SCORE_FIELDS = (
    "relevance_score",
    "novelty_score",
    "evidence_score",
    "reproducibility_score",
    "clarity_score",
    "impact_score",
)


LOG_FILE_PATH: Optional[Path] = None
_LOG_FH: Optional[TextIO] = None


def _close_log_file() -> None:
    global _LOG_FH
    fh = _LOG_FH
    if fh is None:
        return
    try:
        fh.flush()
        fh.close()
    except Exception:
        pass
    _LOG_FH = None


def configure_logging(log_file: Optional[str]) -> None:
    global LOG_FILE_PATH
    global _LOG_FH

    if not log_file:
        return
    if _LOG_FH is not None:
        return

    try:
        resolved = _resolve_path(log_file)
    except Exception:
        resolved = Path(log_file)

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        _LOG_FH = resolved.open("a", encoding="utf-8")
        LOG_FILE_PATH = resolved
    except Exception as exc:
        print(f"[WARN] Failed to open log file {log_file}: {exc}", file=sys.stderr, flush=True)
        LOG_FILE_PATH = None
        _LOG_FH = None
        return

    atexit.register(_close_log_file)
    header_ts = datetime.now(CST_TZ).strftime("%Y-%m-%d %H:%M:%S")
    try:
        _LOG_FH.write(f"\n===== AIResearch run start {header_ts} CST pid={os.getpid()} =====\n")
        _LOG_FH.flush()
    except Exception:
        pass


def _log(level: str, message: str) -> None:
    ts = datetime.now(CST_TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts} CST] [{level}] {message}"
    print(line, flush=True)
    if _LOG_FH is not None:
        try:
            _LOG_FH.write(f"{line}\n")
            _LOG_FH.flush()
        except Exception:
            pass


def _log_exception(context: str, exc: BaseException) -> None:
    tb = traceback.format_exc()
    message = f"{context}: {exc}".rstrip()
    if tb.strip() and tb.strip() != "NoneType: None":
        message = f"{message}\n{tb}".rstrip()
    _log("ERROR", message)


ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
ARXIV_ID_IN_TEXT_RE = re.compile(r"(\d{4}\.\d{4,5}(v\d+)?)")
ARXIV_VERSION_RE = re.compile(r"v\d+$")

# Tool schema for a custom GitHub scanner (if you wrap your own MCP tool)
GITHUB_CODE_CHECK_TOOL_SCHEMA = {
    "name": "github_scan_repo",
    "description": "Scan a GitHub repo for reproducibility signals.",
    "parameters": {
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "ref": {
                "type": "string",
                "description": "Branch, tag, or SHA (default: main).",
            },
            "max_depth": {
                "type": "integer",
                "description": "Optional tree depth limit.",
            },
        },
        "required": ["owner", "repo"],
    },
}


@dataclass(frozen=True)
class DateWindow:
    start_date: date
    end_date: date
    timezone: timezone = CST_TZ

    def contains(self, value: Optional[datetime]) -> bool:
        if value is None:
            return True
        local = value.astimezone(self.timezone).date()
        return self.start_date <= local <= self.end_date


@dataclass
class Paper:
    paper_id: str
    canonical_id: str
    title: str
    authors: List[str]
    abstract: str
    url: str
    pdf_url: str
    published: datetime
    source: str
    source_tags: Set[str]
    hf_score: Optional[float] = None
    submitted_on_daily: Optional[datetime] = None


@dataclass(init=False)
class PreparedPaper:
    paper: Paper
    whitelisted: bool
    super_whitelist_hit: bool
    super_whitelist_hit_reasons: List[str]
    citation_velocity: float
    source_text: str
    source_path: str
    source_backend: str
    pdf_path: str
    mineru_batch_id: str
    stage1_score: float
    topic_score: float
    coverage_score: float
    clean_exception: bool
    clean_exception_reason: str

    def __init__(
        self,
        paper: Paper,
        whitelisted: bool,
        super_whitelist_hit: bool,
        super_whitelist_hit_reasons: List[str],
        citation_velocity: float,
        source_text: str = "",
        source_path: str = "",
        source_backend: str = "",
        pdf_path: str = "",
        mineru_batch_id: str = "",
        stage1_score: float = 0.0,
        topic_score: float = 0.0,
        coverage_score: float = 0.0,
        clean_exception: bool = False,
        clean_exception_reason: str = "",
        source_markdown: Optional[str] = None,
        source_markdown_path: Optional[str] = None,
    ) -> None:
        self.paper = paper
        self.whitelisted = whitelisted
        self.super_whitelist_hit = super_whitelist_hit
        self.super_whitelist_hit_reasons = list(super_whitelist_hit_reasons)
        self.citation_velocity = citation_velocity
        self.source_text = source_text if source_text else str(source_markdown or "")
        self.source_path = source_path if source_path else str(source_markdown_path or "")
        self.source_backend = source_backend
        self.pdf_path = pdf_path
        self.mineru_batch_id = mineru_batch_id
        self.stage1_score = stage1_score
        self.topic_score = topic_score
        self.coverage_score = coverage_score
        self.clean_exception = clean_exception
        self.clean_exception_reason = clean_exception_reason

    @property
    def source_markdown(self) -> str:
        return self.source_text

    @property
    def source_markdown_path(self) -> str:
        return self.source_path


# ------------------
# Local tool registry (no MCP stdio)
# ------------------


async def run_sync(fn: Any, **kwargs: Any) -> Any:
    return await anyio.to_thread.run_sync(functools.partial(fn, **kwargs))


def load_config(path: Optional[Path]) -> Dict[str, Any]:
    if not path:
        return {}
    if not path.exists():
        _log("WARN", f"Config not found: {path}")
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else CONFIG_BASE_DIR / path


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def _parse_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _parse_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed


def apply_config(config: Dict[str, Any]) -> None:
    global KEYWORDS
    global TOPIC_KEYWORDS
    global TOPIC_BOOST
    global GENERIC_RLHF_TERMS
    global NEW_PAPER_DAYS
    global CITATION_VELOCITY_THRESHOLD
    global DAYS_BACK
    global ARXIV_QUERY_MAX_TERMS
    global ARXIV_MAX_RESULTS_PER_QUERY
    global HF_TRENDING_LIMIT
    global HF_DATE_FIELD
    global STAGE1_PREFILTER_ENABLED
    global STAGE1_TOP_N
    global STAGE1_MIN_SCORE
    global STAGE1_FALLBACK_TOP_K
    global CODEX_CANDIDATE_SCORE_THRESHOLD
    global CANDIDATE_RELEVANCE_MIN
    global CANDIDATE_EVIDENCE_MIN
    global CANDIDATE_SCORE_WEIGHTS
    global WHITELIST_BONUS
    global FRONTIER_YEAR_START
    global FRONTIER_YEAR_END
    global WHITELIST_PATH
    global SUPER_WHITELIST_PATH
    global SUPER_WHITELIST_ENABLED_MAIN
    global SUPER_WHITELIST_TEXT_LIMIT
    global SUPER_WHITELIST_FORCE_NOTIFY
    global SUPER_WHITELIST_MIN_ALIAS_LEN
    global SEEN_CACHE_PATH
    global OUTPUT_ROOT
    global OBSIDIAN_NOTE_DIR
    global STATE_DIR
    global LAST_RUN_PATH
    global EMAIL_RECIPIENTS
    global EMAIL_SUBJECT_PREFIX
    global EMAIL_ACCOUNT_NAME
    global CODEX_PROMPT_PAPER_ANALYSIS_PATH
    global CODEX_PROMPT_CANDIDATE_PATH
    global MINERU_POLL_INTERVAL_SEC
    global MINERU_PER_RUN_TIMEOUT_SEC
    global MINERU_MAX_ATTEMPTS
    global MINERU_BACKOFF_BASE_SEC
    global CODEX_TIMEOUT_SEC
    global CODEX_CHUNK_CHARS
    global CODEX_CHUNK_OVERLAP
    global CODEX_SKIP_GIT_REPO_CHECK
    global CODEX_USE_SEARCH
    global CODEX_MAX_CONCURRENCY
    global PAPER_EVAL_CONCURRENCY
    global GITHUB_SCAN_MAX
    global OBSIDIAN_VAULT
    global _CODEX_SEMAPHORE

    if isinstance(config.get("keywords"), list) and config["keywords"]:
        KEYWORDS = [str(v) for v in config["keywords"] if str(v).strip()]
        _log("INFO", f"Config keywords set: {len(KEYWORDS)} terms")
    if isinstance(config.get("topic_keywords"), dict):
        TOPIC_KEYWORDS = {
            str(k): [str(vv) for vv in v] if isinstance(v, list) else []
            for k, v in config["topic_keywords"].items()
        }
        _log("INFO", f"Config topic_keywords set: {len(TOPIC_KEYWORDS)} groups")
    if isinstance(config.get("topic_boost"), dict):
        TOPIC_BOOST = {str(k): float(v) for k, v in config["topic_boost"].items()}
        _log("INFO", "Config topic_boost loaded")
    if isinstance(config.get("generic_rlhf_terms"), list):
        GENERIC_RLHF_TERMS = [str(v) for v in config["generic_rlhf_terms"] if str(v).strip()]
        _log("INFO", f"Config generic_rlhf_terms set: {len(GENERIC_RLHF_TERMS)} terms")

    if "new_paper_days" in config:
        _log(
            "WARN",
            f"Config new_paper_days is deprecated and ignored in base filter (received {config['new_paper_days']})",
        )
    if "citation_velocity_threshold" in config:
        _log(
            "WARN",
            "Config citation_velocity_threshold is deprecated and ignored in base filter "
            f"(received {config['citation_velocity_threshold']})",
        )

    if "days_back" in config:
        DAYS_BACK = max(1, _parse_int(config["days_back"], DAYS_BACK))
        _log("INFO", f"Config days_back: {DAYS_BACK}")
    if "arxiv_query_max_terms" in config:
        ARXIV_QUERY_MAX_TERMS = max(1, _parse_int(config["arxiv_query_max_terms"], ARXIV_QUERY_MAX_TERMS))
        _log("INFO", f"Config arxiv_query_max_terms: {ARXIV_QUERY_MAX_TERMS}")
    if "arxiv_max_results_per_query" in config:
        ARXIV_MAX_RESULTS_PER_QUERY = max(
            1,
            _parse_int(config["arxiv_max_results_per_query"], ARXIV_MAX_RESULTS_PER_QUERY),
        )
        _log("INFO", f"Config arxiv_max_results_per_query: {ARXIV_MAX_RESULTS_PER_QUERY}")
    if "hf_trending_limit" in config:
        HF_TRENDING_LIMIT = max(1, _parse_int(config["hf_trending_limit"], HF_TRENDING_LIMIT))
        _log("INFO", f"Config hf_trending_limit: {HF_TRENDING_LIMIT}")
    if "hf_date_field" in config:
        HF_DATE_FIELD = str(config["hf_date_field"]).strip() or HF_DATE_FIELD
        _log("INFO", f"Config hf_date_field: {HF_DATE_FIELD}")

    if "stage1_prefilter_enabled" in config:
        STAGE1_PREFILTER_ENABLED = _parse_bool(config["stage1_prefilter_enabled"])
        _log("INFO", f"Config stage1_prefilter_enabled: {STAGE1_PREFILTER_ENABLED}")
    if "stage1_top_n" in config:
        STAGE1_TOP_N = max(1, _parse_int(config["stage1_top_n"], STAGE1_TOP_N))
        _log("INFO", f"Config stage1_top_n: {STAGE1_TOP_N}")
    if "stage1_min_score" in config:
        STAGE1_MIN_SCORE = _parse_float(config["stage1_min_score"], STAGE1_MIN_SCORE)
        _log("INFO", f"Config stage1_min_score: {STAGE1_MIN_SCORE}")
    if "stage1_fallback_top_k" in config:
        STAGE1_FALLBACK_TOP_K = max(1, _parse_int(config["stage1_fallback_top_k"], STAGE1_FALLBACK_TOP_K))
        _log("INFO", f"Config stage1_fallback_top_k: {STAGE1_FALLBACK_TOP_K}")

    if "codex_candidate_score_threshold" in config:
        CODEX_CANDIDATE_SCORE_THRESHOLD = _parse_float(
            config["codex_candidate_score_threshold"],
            CODEX_CANDIDATE_SCORE_THRESHOLD,
        )
        _log("INFO", f"Config codex_candidate_score_threshold: {CODEX_CANDIDATE_SCORE_THRESHOLD}")
    if "candidate_relevance_min" in config:
        CANDIDATE_RELEVANCE_MIN = _parse_float(config["candidate_relevance_min"], CANDIDATE_RELEVANCE_MIN)
        _log("INFO", f"Config candidate_relevance_min: {CANDIDATE_RELEVANCE_MIN}")
    if "candidate_evidence_min" in config:
        CANDIDATE_EVIDENCE_MIN = _parse_float(config["candidate_evidence_min"], CANDIDATE_EVIDENCE_MIN)
        _log("INFO", f"Config candidate_evidence_min: {CANDIDATE_EVIDENCE_MIN}")
    if isinstance(config.get("candidate_score_weights"), dict):
        merged = dict(CANDIDATE_SCORE_WEIGHTS)
        for key, value in config["candidate_score_weights"].items():
            if key in CANDIDATE_SCORE_WEIGHTS:
                merged[key] = _parse_float(value, merged[key])
        CANDIDATE_SCORE_WEIGHTS = merged
        _log("INFO", "Config candidate_score_weights loaded")

    if "whitelist_bonus" in config:
        WHITELIST_BONUS = _parse_float(config["whitelist_bonus"], WHITELIST_BONUS)
        _log("INFO", f"Config whitelist_bonus: {WHITELIST_BONUS}")
    if "frontier_year_start" in config:
        FRONTIER_YEAR_START = _parse_int(config["frontier_year_start"], FRONTIER_YEAR_START)
        _log("INFO", f"Config frontier_year_start: {FRONTIER_YEAR_START}")
    if "frontier_year_end" in config:
        FRONTIER_YEAR_END = _parse_int(config["frontier_year_end"], FRONTIER_YEAR_END)
        _log("INFO", f"Config frontier_year_end: {FRONTIER_YEAR_END}")

    if "whitelist_path" in config:
        WHITELIST_PATH = _resolve_path(str(config["whitelist_path"]))
        _log("INFO", f"Config whitelist_path: {WHITELIST_PATH}")
    if "super_whitelist_path" in config:
        SUPER_WHITELIST_PATH = _resolve_path(str(config["super_whitelist_path"]))
        _log("INFO", f"Config super_whitelist_path: {SUPER_WHITELIST_PATH}")
    if "super_whitelist_enabled_main" in config:
        SUPER_WHITELIST_ENABLED_MAIN = _parse_bool(config["super_whitelist_enabled_main"])
        _log("INFO", f"Config super_whitelist_enabled_main: {SUPER_WHITELIST_ENABLED_MAIN}")
    if "super_whitelist_text_limit" in config:
        SUPER_WHITELIST_TEXT_LIMIT = max(
            100,
            _parse_int(config["super_whitelist_text_limit"], SUPER_WHITELIST_TEXT_LIMIT),
        )
        _log("INFO", f"Config super_whitelist_text_limit: {SUPER_WHITELIST_TEXT_LIMIT}")
    if "super_whitelist_force_notify" in config:
        SUPER_WHITELIST_FORCE_NOTIFY = _parse_bool(config["super_whitelist_force_notify"])
        _log("INFO", f"Config super_whitelist_force_notify: {SUPER_WHITELIST_FORCE_NOTIFY}")
    if "super_whitelist_min_alias_len" in config:
        SUPER_WHITELIST_MIN_ALIAS_LEN = max(
            1,
            _parse_int(config["super_whitelist_min_alias_len"], SUPER_WHITELIST_MIN_ALIAS_LEN),
        )
        _log("INFO", f"Config super_whitelist_min_alias_len: {SUPER_WHITELIST_MIN_ALIAS_LEN}")

    if "seen_cache_path" in config:
        parsed_seen_cache_path = _resolve_path(str(config["seen_cache_path"]))
        _log(
            "WARN",
            "Config seen_cache_path is deprecated and ignored; history sent-paper "
            f"dedupe is disabled (received {parsed_seen_cache_path})",
        )
    if "output_root" in config:
        OUTPUT_ROOT = _resolve_path(str(config["output_root"]))
        _log("INFO", f"Config output_root: {OUTPUT_ROOT}")
    if "obsidian_note_dir" in config:
        OBSIDIAN_NOTE_DIR = str(config["obsidian_note_dir"])
        _log("INFO", f"Config obsidian_note_dir: {OBSIDIAN_NOTE_DIR}")
    if "state_dir" in config:
        STATE_DIR = _resolve_path(str(config["state_dir"]))
        LAST_RUN_PATH = STATE_DIR / "last_run.json"
        _log("INFO", f"Config state_dir: {STATE_DIR}")
    if "last_run_path" in config:
        LAST_RUN_PATH = _resolve_path(str(config["last_run_path"]))
        _log("INFO", f"Config last_run_path: {LAST_RUN_PATH}")

    if "email_recipients" in config:
        recipients = config["email_recipients"]
        if isinstance(recipients, list):
            EMAIL_RECIPIENTS[:] = [str(r).strip() for r in recipients if str(r).strip()]
        elif isinstance(recipients, str):
            parts = [p.strip() for p in recipients.replace(";", ",").split(",")]
            EMAIL_RECIPIENTS[:] = [p for p in parts if p]
        _log("INFO", f"Config email_recipients count: {len(EMAIL_RECIPIENTS)}")
    if "email_subject_prefix" in config:
        EMAIL_SUBJECT_PREFIX = str(config["email_subject_prefix"])
        _log("INFO", f"Config email_subject_prefix: {EMAIL_SUBJECT_PREFIX}")
    if "email_account_name" in config:
        EMAIL_ACCOUNT_NAME = str(config["email_account_name"])
        os.environ["EMAIL_ACCOUNT_NAME"] = EMAIL_ACCOUNT_NAME
        _log("INFO", f"Config email_account_name: {EMAIL_ACCOUNT_NAME}")
    if "email_backend" in config:
        os.environ["EMAIL_BACKEND"] = str(config["email_backend"])
        _log("INFO", f"Config email_backend: {os.environ['EMAIL_BACKEND']}")

    if "codex_prompt_chunk_path" in config:
        deprecated_path = _resolve_path(str(config["codex_prompt_chunk_path"]))
        _log("WARN", f"Config codex_prompt_chunk_path is deprecated and ignored in MinerU mode ({deprecated_path})")
    if "codex_prompt_score_path" in config:
        deprecated_path = _resolve_path(str(config["codex_prompt_score_path"]))
        _log("WARN", f"Config codex_prompt_score_path is deprecated and ignored in MinerU mode ({deprecated_path})")
    if "codex_prompt_main_path" in config:
        deprecated_path = _resolve_path(str(config["codex_prompt_main_path"]))
        _log("WARN", f"Config codex_prompt_main_path is deprecated and ignored in MinerU mode ({deprecated_path})")
    if "codex_prompt_candidate_path" in config:
        CODEX_PROMPT_CANDIDATE_PATH = _resolve_path(str(config["codex_prompt_candidate_path"]))
        _log("INFO", f"Config codex_prompt_candidate_path: {CODEX_PROMPT_CANDIDATE_PATH}")
    if "codex_prompt_clean_path" in config:
        deprecated_path = _resolve_path(str(config["codex_prompt_clean_path"]))
        _log("WARN", f"Config codex_prompt_clean_path is deprecated and ignored in MinerU mode ({deprecated_path})")
    if "codex_prompt_markdown_path" in config:
        deprecated_path = _resolve_path(str(config["codex_prompt_markdown_path"]))
        _log("WARN", f"Config codex_prompt_markdown_path is deprecated and ignored in MinerU mode ({deprecated_path})")
    if "codex_prompt_paper_analysis_path" in config:
        CODEX_PROMPT_PAPER_ANALYSIS_PATH = _resolve_path(str(config["codex_prompt_paper_analysis_path"]))
        _log("INFO", f"Config codex_prompt_paper_analysis_path: {CODEX_PROMPT_PAPER_ANALYSIS_PATH}")
    if "mineru_poll_interval_sec" in config:
        MINERU_POLL_INTERVAL_SEC = max(0, _parse_int(config["mineru_poll_interval_sec"], MINERU_POLL_INTERVAL_SEC))
        _log("INFO", f"Config mineru_poll_interval_sec: {MINERU_POLL_INTERVAL_SEC}")
    if "mineru_per_run_timeout_sec" in config:
        MINERU_PER_RUN_TIMEOUT_SEC = max(1, _parse_int(config["mineru_per_run_timeout_sec"], MINERU_PER_RUN_TIMEOUT_SEC))
        _log("INFO", f"Config mineru_per_run_timeout_sec: {MINERU_PER_RUN_TIMEOUT_SEC}")
    if "mineru_max_attempts" in config:
        MINERU_MAX_ATTEMPTS = max(1, _parse_int(config["mineru_max_attempts"], MINERU_MAX_ATTEMPTS))
        _log("INFO", f"Config mineru_max_attempts: {MINERU_MAX_ATTEMPTS}")
    if "mineru_backoff_base_sec" in config:
        MINERU_BACKOFF_BASE_SEC = max(0.0, _parse_float(config["mineru_backoff_base_sec"], MINERU_BACKOFF_BASE_SEC))
        _log("INFO", f"Config mineru_backoff_base_sec: {MINERU_BACKOFF_BASE_SEC}")
    if "codex_timeout_sec" in config:
        CODEX_TIMEOUT_SEC = max(10, _parse_int(config["codex_timeout_sec"], CODEX_TIMEOUT_SEC))
        _log("INFO", f"Config codex_timeout_sec: {CODEX_TIMEOUT_SEC}")
    if "codex_chunk_chars" in config:
        parsed_chunk_chars = max(500, _parse_int(config["codex_chunk_chars"], CODEX_CHUNK_CHARS))
        _log(
            "WARN",
            "Config codex_chunk_chars is deprecated and ignored in single-pass mode "
            f"(received {parsed_chunk_chars})",
        )
    if "codex_chunk_overlap" in config:
        parsed_chunk_overlap = max(0, _parse_int(config["codex_chunk_overlap"], CODEX_CHUNK_OVERLAP))
        _log(
            "WARN",
            "Config codex_chunk_overlap is deprecated and ignored in single-pass mode "
            f"(received {parsed_chunk_overlap})",
        )
    if "codex_skip_git_repo_check" in config:
        CODEX_SKIP_GIT_REPO_CHECK = _parse_bool(config["codex_skip_git_repo_check"])
        _log("INFO", f"Config codex_skip_git_repo_check: {CODEX_SKIP_GIT_REPO_CHECK}")
    if "codex_use_search" in config:
        CODEX_USE_SEARCH = _parse_bool(config["codex_use_search"])
        _log("INFO", f"Config codex_use_search: {CODEX_USE_SEARCH}")
    if "codex_max_concurrency" in config:
        CODEX_MAX_CONCURRENCY = max(1, _parse_int(config["codex_max_concurrency"], CODEX_MAX_CONCURRENCY))
        _log("INFO", f"Config codex_max_concurrency: {CODEX_MAX_CONCURRENCY}")
    if "paper_eval_concurrency" in config:
        PAPER_EVAL_CONCURRENCY = max(1, _parse_int(config["paper_eval_concurrency"], PAPER_EVAL_CONCURRENCY))
        _log("INFO", f"Config paper_eval_concurrency: {PAPER_EVAL_CONCURRENCY}")
    if "github_scan_max" in config:
        GITHUB_SCAN_MAX = max(1, _parse_int(config["github_scan_max"], GITHUB_SCAN_MAX))
        _log("INFO", f"Config github_scan_max: {GITHUB_SCAN_MAX}")
    if "obsidian_vault" in config:
        OBSIDIAN_VAULT = str(config["obsidian_vault"])
        os.environ["OBSIDIAN_VAULT"] = OBSIDIAN_VAULT
        _log("INFO", f"Config obsidian_vault: {OBSIDIAN_VAULT}")

    # Invalidate semaphore so new limit can take effect.
    _CODEX_SEMAPHORE = None


def _cst_today_str() -> str:
    return datetime.now(timezone.utc).astimezone(CST_TZ).strftime("%Y-%m-%d")


def load_last_run(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return data.get("date")
    return None


def save_last_run(path: Path, date_str: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": date_str}), encoding="utf-8")


# ------------------
# Date window
# ------------------


def _parse_cli_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _resolve_date_window(
    cli_days_back: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
) -> DateWindow:
    if bool(start_date) != bool(end_date):
        raise ValueError("start-date and end-date must be provided together")

    if start_date and end_date:
        start = _parse_cli_date(start_date)
        end = _parse_cli_date(end_date)
        if start > end:
            raise ValueError("start-date is after end-date")
        return DateWindow(start_date=start, end_date=end)

    days = cli_days_back if cli_days_back is not None else DAYS_BACK
    days = max(1, days)
    end = datetime.now(timezone.utc).astimezone(CST_TZ).date()
    start = end - timedelta(days=days - 1)
    return DateWindow(start_date=start, end_date=end)


def _window_days(window: DateWindow) -> int:
    return (window.end_date - window.start_date).days + 1


def _parse_datetime_maybe(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _parse_published(value: Any) -> datetime:
    dt = _parse_datetime_maybe(value)
    return dt if dt else datetime.now(timezone.utc)


def _paper_time_for_field(paper: Paper, field_name: str) -> Optional[datetime]:
    if field_name == "submitted_on_daily" and paper.submitted_on_daily:
        return paper.submitted_on_daily
    return paper.published


def _paper_in_date_window(paper: Paper, window: DateWindow, field_name: str) -> bool:
    return window.contains(_paper_time_for_field(paper, field_name))


# ------------------
# Filters / normalization
# ------------------


def _normalize_author(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9 ]", " ", name)).strip().lower()


def _normalize_alias(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9 ]", " ", value)).strip().lower()


def _safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_")


def load_whitelist(path: Path) -> Set[str]:
    if not path.exists():
        _log("WARN", f"Whitelist not found: {path}")
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        authors = data.get("authors", [])
    elif isinstance(data, list):
        authors = data
    else:
        authors = []
    return {_normalize_author(a) for a in authors}


def load_super_whitelist(path: Path) -> Dict[str, Set[str]]:
    if not path.exists():
        _log("WARN", f"Super whitelist not found: {path}")
        return {"authors": set(), "institutions": set()}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"authors": set(), "institutions": set()}
    authors_raw = data.get("authors", [])
    institutions_raw = data.get("institutions", [])
    authors = {
        _normalize_alias(v)
        for v in authors_raw
        if isinstance(v, str) and len(_normalize_alias(v)) >= SUPER_WHITELIST_MIN_ALIAS_LEN
    }
    institutions = {
        _normalize_alias(v)
        for v in institutions_raw
        if isinstance(v, str) and len(_normalize_alias(v)) >= SUPER_WHITELIST_MIN_ALIAS_LEN
    }
    return {"authors": authors, "institutions": institutions}


def author_in_whitelist(authors: Iterable[str], whitelist: Set[str]) -> bool:
    return any(_normalize_author(a) in whitelist for a in authors)


def _strip_arxiv_version(value: str) -> str:
    return ARXIV_VERSION_RE.sub("", value)


def _extract_arxiv_like_id(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"arxiv\.org/(abs|pdf)/(\d{4}\.\d{4,5}(v\d+)?)", text, re.IGNORECASE)
    if match:
        return match.group(2)
    match = ARXIV_ID_IN_TEXT_RE.search(text)
    if match:
        return match.group(1)
    return None


def _normalize_arxiv_like_id(value: str) -> Optional[str]:
    if not value:
        return None
    raw = value.strip()
    if raw.lower().startswith("arxiv:"):
        raw = raw.split(":", 1)[1]
    if "/" in raw:
        tail = raw.rsplit("/", 1)[-1]
        if ARXIV_ID_RE.match(tail):
            raw = tail
    match = ARXIV_ID_IN_TEXT_RE.search(raw)
    if match:
        return _strip_arxiv_version(match.group(1))
    return None


def _build_canonical_id(
    paper_id: str,
    title: str,
    url: str,
    pdf_url: str,
    abstract: str,
) -> str:
    normalized = _normalize_arxiv_like_id(paper_id)
    if normalized:
        return normalized
    for text in (url, pdf_url, abstract):
        extracted = _extract_arxiv_like_id(text)
        if extracted:
            return _strip_arxiv_version(extracted)
    base = (title or url or paper_id or abstract).strip().lower()
    if not base:
        base = "unknown-paper"
    return f"sha1:{hashlib.sha1(base.encode('utf-8')).hexdigest()}"


def _extract_arxiv_id(paper: Paper) -> Optional[str]:
    normalized = _normalize_arxiv_like_id(paper.paper_id)
    if normalized:
        return normalized
    normalized = _normalize_arxiv_like_id(paper.canonical_id)
    if normalized:
        return normalized
    for text in (paper.url, paper.pdf_url, paper.abstract):
        extracted = _extract_arxiv_like_id(text)
        if extracted:
            return _strip_arxiv_version(extracted)
    return None


def _paper_age_days(published: datetime) -> int:
    now = datetime.now(timezone.utc)
    return max(0, (now - published).days)


async def get_citation_velocity(paper: Paper) -> float:
    paper_lookup_id = _extract_arxiv_id(paper) or paper.paper_id or paper.canonical_id
    try:
        response = await run_sync(scholarly_mcp.paper_lookup, paper_id=paper_lookup_id)
    except Exception as exc:
        _log("WARN", f"Citation lookup failed for {paper.canonical_id}: {exc}")
        return 0.0
    if response.get("rateLimited"):
        _log("WARN", f"Semantic Scholar rate-limited; using 0 citations for {paper.canonical_id}")
    citation_count = response.get("citationCount", 0)
    age_days = _paper_age_days(paper.published)
    months = max(1.0, age_days / 30.0)
    _log("INFO", f"Citation velocity for {paper.canonical_id}: {citation_count}/{months:.1f} months")
    return citation_count / months


def _match_terms(terms: Iterable[str], text: str) -> bool:
    low = text.lower()
    return any(term.lower() in low for term in terms if term)


def compute_topic_score(text: str) -> float:
    score = 0.0
    matched_any = False
    for key, terms in TOPIC_KEYWORDS.items():
        if _match_terms(terms, text):
            matched_any = True
            score += float(TOPIC_BOOST.get(key, 0.0))
    if not matched_any and _match_terms(GENERIC_RLHF_TERMS, text):
        score += float(TOPIC_BOOST.get("generic_penalty", 0.0))
    return score


async def passes_filters(paper: Paper, whitelist: Set[str]) -> Tuple[bool, float, bool]:
    if author_in_whitelist(paper.authors, whitelist):
        _log("INFO", f"Filter pass by whitelist: {paper.canonical_id}")
        return True, 0.0, True

    _log("INFO", f"Filter pass (base age/citation checks disabled): {paper.canonical_id}")
    return True, 0.0, False


def super_whitelist_hit(
    paper: Paper,
    super_whitelist: Dict[str, Set[str]],
) -> Tuple[bool, List[str]]:
    if not SUPER_WHITELIST_ENABLED_MAIN:
        return False, []

    hits: List[str] = []
    normalized_authors = {_normalize_alias(a) for a in paper.authors}
    for alias in super_whitelist.get("authors", set()):
        if alias in normalized_authors:
            hits.append(f"author:{alias}")

    text = f"{paper.title} {paper.abstract}".strip()
    text = text[:SUPER_WHITELIST_TEXT_LIMIT]
    normalized_text = _normalize_alias(text)
    for alias in super_whitelist.get("institutions", set()):
        if alias and alias in normalized_text:
            hits.append(f"institution:{alias}")

    return bool(hits), hits


# ------------------
# Discovery
# ------------------


def _query_chunks(terms: List[str], chunk_size: int) -> List[List[str]]:
    cleaned = [t.strip() for t in terms if t and t.strip()]
    if not cleaned:
        return []
    size = max(1, chunk_size)
    return [cleaned[i : i + size] for i in range(0, len(cleaned), size)]


def _build_or_query(terms: List[str]) -> str:
    return " OR ".join(terms)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_paper_from_arxiv(item: Dict[str, Any], source_tag: str) -> Paper:
    raw_id = str(item.get("id", "")).strip()
    title = str(item.get("title", "")).strip()
    abstract = str(item.get("summary", item.get("abstract", ""))).strip()
    url = str(item.get("url", "")).strip()
    pdf_url = str(item.get("pdf_url", "")).strip()
    canonical_id = _build_canonical_id(raw_id, title, url, pdf_url, abstract)
    return Paper(
        paper_id=raw_id or canonical_id,
        canonical_id=canonical_id,
        title=title,
        authors=[str(a).strip() for a in item.get("authors", []) if str(a).strip()],
        abstract=abstract,
        url=url,
        pdf_url=pdf_url,
        published=_parse_published(item.get("published")),
        source="arxiv",
        source_tags={source_tag},
        hf_score=None,
        submitted_on_daily=None,
    )


def _build_paper_from_hf(item: Dict[str, Any], source_tag: str) -> Paper:
    raw_id = str(item.get("id", "")).strip()
    title = str(item.get("title", "")).strip()
    abstract = str(item.get("abstract", item.get("summary", ""))).strip()
    url = str(item.get("url", "")).strip()
    pdf_url = str(item.get("pdf_url", "")).strip()
    canonical_id = _build_canonical_id(raw_id, title, url, pdf_url, abstract)
    raw_score = item.get("score") or item.get("likes") or item.get("upvotes") or 0
    submitted = _parse_datetime_maybe(item.get("submitted_on_daily"))
    return Paper(
        paper_id=raw_id or canonical_id,
        canonical_id=canonical_id,
        title=title,
        authors=[str(a).strip() for a in item.get("authors", []) if str(a).strip()],
        abstract=abstract,
        url=url,
        pdf_url=pdf_url,
        published=_parse_published(item.get("published")),
        source="hf_papers",
        source_tags={source_tag},
        hf_score=_as_float(raw_score, 0.0),
        submitted_on_daily=submitted,
    )


def _merge_papers(existing: Paper, incoming: Paper) -> None:
    if not existing.title and incoming.title:
        existing.title = incoming.title
    if len(incoming.title) > len(existing.title):
        existing.title = incoming.title
    if not existing.abstract and incoming.abstract:
        existing.abstract = incoming.abstract
    if len(incoming.abstract) > len(existing.abstract):
        existing.abstract = incoming.abstract
    if not existing.authors and incoming.authors:
        existing.authors = incoming.authors
    if not existing.url and incoming.url:
        existing.url = incoming.url
    if not existing.pdf_url and incoming.pdf_url:
        existing.pdf_url = incoming.pdf_url
    if incoming.hf_score is not None:
        existing.hf_score = max(existing.hf_score or 0.0, incoming.hf_score)
    if incoming.submitted_on_daily and (
        existing.submitted_on_daily is None or incoming.submitted_on_daily > existing.submitted_on_daily
    ):
        existing.submitted_on_daily = incoming.submitted_on_daily
    if incoming.published > existing.published:
        existing.published = incoming.published
    existing.source_tags.update(incoming.source_tags)
    existing.source = ",".join(sorted(existing.source_tags))
    if existing.paper_id.startswith("sha1:") and not incoming.paper_id.startswith("sha1:"):
        existing.paper_id = incoming.paper_id


async def discover_papers(window: DateWindow) -> List[Paper]:
    chunks = _query_chunks(KEYWORDS, ARXIV_QUERY_MAX_TERMS)
    if not chunks:
        _log("WARN", "No keywords configured. Discovery returned empty.")
        return []

    merged: Dict[str, Paper] = {}
    hf_days_back = max(_window_days(window), DAYS_BACK)

    for idx, terms in enumerate(chunks, 1):
        query = _build_or_query(terms)
        _log("INFO", f"Discovery chunk {idx}/{len(chunks)} query: {query}")

        try:
            arxiv_results = await run_sync(
                arxiv_mcp.search,
                query=query,
                max_results=ARXIV_MAX_RESULTS_PER_QUERY,
            )
        except Exception as exc:
            _log("WARN", f"arXiv query failed for chunk {idx}: {exc}")
            arxiv_results = []

        try:
            hf_results = await run_sync(
                hf_papers_mcp.papers_search,
                query=query,
                limit=ARXIV_MAX_RESULTS_PER_QUERY,
                days_back=hf_days_back,
            )
        except Exception as exc:
            _log("WARN", f"HF daily query failed for chunk {idx}: {exc}")
            hf_results = []

        _log("INFO", f"Chunk {idx}: arXiv={len(arxiv_results)} HF-daily={len(hf_results)}")

        for item in arxiv_results:
            paper = _build_paper_from_arxiv(item, "arxiv")
            existing = merged.get(paper.canonical_id)
            if existing:
                _merge_papers(existing, paper)
            else:
                merged[paper.canonical_id] = paper

        for item in hf_results:
            paper = _build_paper_from_hf(item, "hf_papers")
            existing = merged.get(paper.canonical_id)
            if existing:
                _merge_papers(existing, paper)
            else:
                merged[paper.canonical_id] = paper

    trending_query = _build_or_query(KEYWORDS)
    try:
        trending_results = await run_sync(
            hf_papers_mcp.papers_trending,
            query=trending_query,
            limit=HF_TRENDING_LIMIT,
        )
    except Exception as exc:
        _log("WARN", f"HF trending query failed: {exc}")
        trending_results = []
    _log("INFO", f"HF trending results: {len(trending_results)}")

    for item in trending_results:
        paper = _build_paper_from_hf(item, "hf_trending")
        existing = merged.get(paper.canonical_id)
        if existing:
            _merge_papers(existing, paper)
        else:
            merged[paper.canonical_id] = paper

    filtered: List[Paper] = []
    for paper in merged.values():
        if _paper_in_date_window(paper, window, HF_DATE_FIELD):
            paper.source = ",".join(sorted(paper.source_tags))
            filtered.append(paper)

    _log("INFO", f"Discovery merged={len(merged)} after-date-filter={len(filtered)}")
    return filtered


# ------------------
# Stage1 prefilter (title + abstract)
# ------------------


def _matched_topic_group_count(text: str) -> int:
    if not text:
        return 0
    low = text.lower()
    hits = 0
    for terms in TOPIC_KEYWORDS.values():
        if any(term.lower() in low for term in terms if term):
            hits += 1
    return hits


def _stage1_seed_text(paper: Paper) -> str:
    title = (paper.title or "").strip()
    abstract = (paper.abstract or "").strip()
    if title and abstract:
        return f"{title}\n{abstract}"
    return title or abstract


def compute_stage1_score(clean_text: str) -> Dict[str, float]:
    topic_score = compute_topic_score(clean_text)
    matched_groups = _matched_topic_group_count(clean_text)
    coverage_score = min(1.5, 0.15 * float(matched_groups))
    stage1_score = topic_score + coverage_score
    return {
        "stage1_score": stage1_score,
        "topic_score": topic_score,
        "coverage_score": coverage_score,
    }


def apply_stage1_prefilter(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = sorted(
        entries,
        key=lambda item: (
            item.get("stage1_score", 0.0),
            item.get("topic_score", 0.0),
            item.get("coverage_score", 0.0),
            item["paper"].published,
        ),
        reverse=True,
    )
    if not STAGE1_PREFILTER_ENABLED:
        _log("INFO", f"Stage1 disabled. Keeping {len(ranked)} candidates.")
        return ranked

    top = ranked[:STAGE1_TOP_N]
    qualified = [item for item in top if item.get("stage1_score", 0.0) >= STAGE1_MIN_SCORE]
    if len(qualified) < STAGE1_FALLBACK_TOP_K:
        qualified = top[:STAGE1_FALLBACK_TOP_K]
    _log(
        "INFO",
        f"Stage1 prefilter total={len(entries)} top_n={len(top)} passed={len(qualified)} "
        f"(min_score={STAGE1_MIN_SCORE}, fallback_top_k={STAGE1_FALLBACK_TOP_K})",
    )
    return qualified


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _count_term_hits(text: str, terms: Iterable[str]) -> int:
    low = text.lower()
    return sum(1 for term in terms if term and term.lower() in low)


def _candidate_scores_heuristic(clean_text: str) -> Dict[str, float]:
    topic_score = compute_topic_score(clean_text)
    novelty_hits = _count_term_hits(
        clean_text,
        (
            "we propose",
            "novel",
            "new method",
            "first",
            "introduce",
            "our approach",
        ),
    )
    evidence_hits = _count_term_hits(
        clean_text,
        (
            "benchmark",
            "evaluation",
            "ablation",
            "experiment",
            "results",
            "error analysis",
            "table",
            "figure",
            "baseline",
        ),
    )
    repro_hits = _count_term_hits(
        clean_text,
        (
            "github.com",
            "code",
            "open-source",
            "released",
            "reproduc",
            "implementation",
        ),
    )
    clarity_hits = _count_term_hits(
        clean_text,
        (
            "method",
            "approach",
            "algorithm",
            "setup",
            "experiment",
            "conclusion",
        ),
    )
    impact_hits = _count_term_hits(
        clean_text,
        (
            "state-of-the-art",
            "sota",
            "significant",
            "improve",
            "outperform",
            "scaling",
        ),
    )
    return {
        "relevance_score": _clamp(1.0 + topic_score / 2.0, 1.0, 5.0),
        "novelty_score": _clamp(1.0 + novelty_hits * 0.6, 1.0, 5.0),
        "evidence_score": _clamp(1.0 + evidence_hits * 0.45, 1.0, 5.0),
        "reproducibility_score": _clamp(1.0 + repro_hits * 0.8, 1.0, 5.0),
        "clarity_score": _clamp(1.0 + clarity_hits * 0.4, 1.0, 5.0),
        "impact_score": _clamp(1.0 + impact_hits * 0.5, 1.0, 5.0),
    }


def _extract_candidate_scores(payload: Dict[str, Any], fallback: Dict[str, float]) -> Dict[str, float]:
    out = dict(fallback)
    for field in CANDIDATE_SCORE_FIELDS:
        out[field] = _clamp(_as_float(payload.get(field), out[field]), 1.0, 5.0)
    return out


def _weighted_candidate_score(scores: Dict[str, float]) -> float:
    total_weight = 0.0
    total_score = 0.0
    for field in CANDIDATE_SCORE_FIELDS:
        weight = _as_float(CANDIDATE_SCORE_WEIGHTS.get(field), 0.0)
        total_weight += weight
        total_score += weight * _as_float(scores.get(field), 0.0)
    if total_weight <= 0.0:
        return 0.0
    return total_score / total_weight


async def evaluate_candidate_gate(entry: Dict[str, Any], clean_text: str) -> Dict[str, Any]:
    paper: Paper = entry["paper"]
    normalized = clean_text.strip()
    if not normalized:
        result = {
            "mode": "missing_clean_text",
            "scores": {field: 1.0 for field in CANDIDATE_SCORE_FIELDS},
            "weighted_score": 0.0,
            "passed": False,
            "reason": "clean_fulltext_missing",
        }
        _log("WARN", f"Candidate gate rejected {paper.canonical_id}: missing clean text")
        return result

    fallback_scores = _candidate_scores_heuristic(normalized)
    mode = "heuristic"
    payload: Dict[str, Any] = {}

    if CODEX_PROMPT_CANDIDATE_PATH.exists():
        try:
            template = _load_prompt(CODEX_PROMPT_CANDIDATE_PATH)
            prompt = _render_prompt(
                template,
                title=paper.title,
                authors=", ".join(paper.authors),
                source_tags=", ".join(sorted(paper.source_tags)),
                clean_fulltext=normalized[:40000],
            )
            payload = await _run_codex_json_cached("clean_fulltext", paper, prompt)
            mode = "codex"
        except Exception as exc:
            _log("WARN", f"Candidate gate codex failed for {paper.canonical_id}, fallback to heuristic: {exc}")
    else:
        _log("WARN", f"Candidate prompt missing ({CODEX_PROMPT_CANDIDATE_PATH}), fallback to heuristic.")

    scores = _extract_candidate_scores(payload, fallback_scores)
    weighted = _weighted_candidate_score(scores)
    passed = (
        weighted >= CODEX_CANDIDATE_SCORE_THRESHOLD
        and scores["relevance_score"] >= CANDIDATE_RELEVANCE_MIN
        and scores["evidence_score"] >= CANDIDATE_EVIDENCE_MIN
    )

    result = {
        "mode": mode,
        "scores": scores,
        "weighted_score": weighted,
        "passed": passed,
        "reason": str(payload.get("reason", "")) if payload else "",
    }
    _log(
        "INFO",
        f"Candidate gate {paper.canonical_id}: pass={passed} mode={mode} weighted={weighted:.3f} "
        f"rel={scores['relevance_score']:.2f} evd={scores['evidence_score']:.2f}",
    )
    return result


# ------------------
# Retrieval + LaTeX Source
# ------------------


async def fetch_latex_source(paper: Paper) -> Dict[str, Any]:
    arxiv_id = _extract_arxiv_id(paper)
    if not arxiv_id:
        raise RuntimeError("arXiv ID not found for paper")
    out_dir = OUTPUT_ROOT / "latex"
    _log("INFO", f"Fetching LaTeX source for {arxiv_id}")
    return await run_sync(
        arxiv_mcp.source_fetch,
        arxiv_id=arxiv_id,
        output_dir=str(out_dir),
    )


def _resolve_paper_pdf_url(paper: Paper) -> str:
    pdf_url = (paper.pdf_url or "").strip()
    if pdf_url:
        return pdf_url
    arxiv_id = _extract_arxiv_id(paper)
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return ""


def _download_pdf_attachment_sync(
    pdf_url: str,
    output_path: Path,
    timeout_sec: int = 120,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    req = Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            payload = resp.read()
    except URLError as exc:
        raise RuntimeError(f"PDF download failed: {exc}") from exc
    if not payload:
        raise RuntimeError("PDF download returned empty content")
    output_path.write_bytes(payload)
    return output_path


def _mineru_output_root() -> Path:
    return OUTPUT_ROOT / "mineru"


def _mineru_state_root() -> Path:
    return STATE_DIR / "mineru"


def _is_missing_mineru_key_error(exc: BaseException) -> bool:
    return "MINERU_API_KEY" in str(exc)


def _build_prepared_exception(
    paper: Paper,
    whitelisted: bool,
    super_hit: bool,
    super_hit_reasons: List[str],
    citation_velocity: float,
    stage1_score: float,
    topic_score: float,
    coverage_score: float,
    reason: str,
    *,
    source_text: str = "",
    source_path: str = "",
    source_backend: str = "",
    pdf_path: str = "",
    mineru_batch_id: str = "",
) -> PreparedPaper:
    return PreparedPaper(
        paper=paper,
        whitelisted=whitelisted,
        super_whitelist_hit=super_hit,
        super_whitelist_hit_reasons=super_hit_reasons,
        citation_velocity=citation_velocity,
        source_text=source_text,
        source_path=source_path,
        source_backend=source_backend,
        pdf_path=pdf_path,
        mineru_batch_id=mineru_batch_id,
        stage1_score=stage1_score,
        topic_score=topic_score,
        coverage_score=coverage_score,
        clean_exception=True,
        clean_exception_reason=reason,
    )


async def prepare_pdf_markdown(paper: Paper) -> Dict[str, Any]:
    pdf_url = _resolve_paper_pdf_url(paper)
    if not pdf_url:
        raise RuntimeError(f"PDF URL not found for {paper.canonical_id}")
    _log("INFO", f"Preparing MinerU markdown for {paper.canonical_id}")
    return await run_sync(
        mineru_pdf.convert_pdf_to_markdown,
        canonical_id=paper.canonical_id,
        pdf_url=pdf_url,
        output_root=_mineru_output_root(),
        state_root=_mineru_state_root(),
        poll_interval_sec=MINERU_POLL_INTERVAL_SEC,
        per_run_timeout_sec=MINERU_PER_RUN_TIMEOUT_SEC,
        max_attempts=MINERU_MAX_ATTEMPTS,
        backoff_base_sec=MINERU_BACKOFF_BASE_SEC,
    )


def _select_fallback_tex_path(latex_result: Dict[str, Any]) -> str:
    tex_path = str(latex_result.get("tex_path") or "").strip()
    if tex_path:
        return tex_path
    tex_files = [Path(p) for p in latex_result.get("tex_files", []) if str(p).strip()]
    selected = latex_reader.select_main_tex(tex_files)
    return str(selected) if selected else ""


async def _prepare_from_latex_fallback(
    paper: Paper,
    whitelisted: bool,
    super_hit: bool,
    super_hit_reasons: List[str],
    citation_velocity: float,
    stage1_score: float,
    topic_score: float,
    coverage_score: float,
) -> Optional[PreparedPaper]:
    try:
        latex_result = await fetch_latex_source(paper)
    except Exception as exc:
        if whitelisted:
            reason = f"latex_fetch_failed:{exc}"
            _log("WARN", f"Whitelist exception {paper.canonical_id}: {reason}")
            return _build_prepared_exception(
                paper,
                whitelisted,
                super_hit,
                super_hit_reasons,
                citation_velocity,
                stage1_score,
                topic_score,
                coverage_score,
                reason,
            )
        _log("ERROR", f"LaTeX source fetch failed for {paper.canonical_id}: {exc}")
        return None

    tex_path = _select_fallback_tex_path(latex_result)
    if not tex_path:
        reason = "no_tex_file"
        if whitelisted:
            _log("WARN", f"Whitelist exception {paper.canonical_id}: {reason}")
            return _build_prepared_exception(
                paper,
                whitelisted,
                super_hit,
                super_hit_reasons,
                citation_velocity,
                stage1_score,
                topic_score,
                coverage_score,
                reason,
            )
        _log("WARN", f"No .tex file found for {paper.canonical_id}")
        return None

    try:
        source_text, _used_files = latex_reader.read_latex_tree(Path(tex_path))
    except Exception as exc:
        if whitelisted:
            reason = f"latex_read_failed:{exc}"
            _log("WARN", f"Whitelist exception {paper.canonical_id}: {reason}")
            return _build_prepared_exception(
                paper,
                whitelisted,
                super_hit,
                super_hit_reasons,
                citation_velocity,
                stage1_score,
                topic_score,
                coverage_score,
                reason,
                source_path=tex_path,
            )
        _log("ERROR", f"LaTeX read failed for {paper.canonical_id}: {exc}")
        return None

    return PreparedPaper(
        paper=paper,
        whitelisted=whitelisted,
        super_whitelist_hit=super_hit,
        super_whitelist_hit_reasons=super_hit_reasons,
        citation_velocity=citation_velocity,
        source_text=source_text,
        source_path=tex_path,
        source_backend="latex_fallback",
        stage1_score=stage1_score,
        topic_score=topic_score,
        coverage_score=coverage_score,
    )


# ------------------
# Reproducibility / GitHub
# ------------------


def _normalize_github_url(url: str) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.netloc.lower()
    if host not in ("github.com", "www.github.com"):
        return None
    return f"{parsed.scheme}://{host}{parsed.path}".rstrip("/")


def parse_github_repo(url: str) -> Optional[Tuple[str, str]]:
    normalized = _normalize_github_url(url)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    return owner, repo


def classify_repro_tier(repo_tree: List[str]) -> str:
    has_requirements = any(p.endswith("requirements.txt") for p in repo_tree)
    has_env = any(p.endswith("environment.yml") or p.endswith("environment.yaml") for p in repo_tree)

    train_scripts = [
        p for p in repo_tree
        if re.search(r"(^|/)(train|finetune|run_clm|run_mlm)\.py$", p)
    ]
    demo_scripts = [
        p for p in repo_tree
        if re.search(r"(^|/)(demo|inference|gradio|app)\.py$", p)
    ]

    if train_scripts and (has_requirements or has_env):
        return "Tier: S (Full Trainer)"
    if demo_scripts:
        return "Tier: C (Demo Only)"
    return "Tier: U (Unknown)"


def combine_tiers(tiers: List[str]) -> str:
    if any(t.startswith("Tier: S") for t in tiers):
        return "Tier: S (Full Trainer)"
    if any(t.startswith("Tier: C") for t in tiers):
        return "Tier: C (Demo Only)"
    if tiers:
        return "Tier: U (Unknown)"
    return "Tier: U (No Code Link)"


def _dedupe_urls(urls: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for url in urls:
        normalized = _normalize_github_url(url)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def select_github_urls(
    primary_url: Optional[str],
    candidates: Iterable[str],
    max_count: int,
) -> List[str]:
    ordered: List[str] = []
    if primary_url:
        normalized = _normalize_github_url(primary_url)
        if normalized:
            ordered.append(normalized)
    for url in _dedupe_urls(candidates):
        if url not in ordered:
            ordered.append(url)
        if len(ordered) >= max_count:
            break
    return ordered[:max_count]


async def check_reproducibility(
    paper: Paper,
    github_urls: List[str],
    primary_url: Optional[str],
) -> Tuple[str, List[Dict[str, str]]]:
    selected = select_github_urls(primary_url, github_urls, GITHUB_SCAN_MAX)
    if not selected:
        _log("INFO", f"No GitHub repo found for {paper.canonical_id}")
        return "Tier: U (No Code Link)", []

    tiers: List[str] = []
    scanned: List[Dict[str, str]] = []
    for url in selected:
        repo = parse_github_repo(url)
        if not repo:
            continue
        owner, repo_name = repo
        _log("INFO", f"Scanning GitHub repo {owner}/{repo_name}")
        try:
            tree = await run_sync(
                github_mcp.repo_tree,
                owner=owner,
                repo=repo_name,
                ref="main",
            )
        except Exception as exc:
            _log("WARN", f"GitHub scan failed for {owner}/{repo_name}: {exc}")
            continue
        tier = classify_repro_tier(tree)
        tiers.append(tier)
        scanned.append({"url": url, "tier": tier})

    overall = combine_tiers(tiers)
    _log("INFO", f"Repro tier for {paper.canonical_id}: {overall}")
    return overall, scanned


# ------------------
# Summarization + Candidate/Codex
# ------------------


def _load_prompt(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _render_prompt(template: str, **kwargs: str) -> str:
    # Escape all braces to preserve JSON/LaTeX in templates, then unescape known placeholders.
    escaped = template.replace("{", "{{").replace("}", "}}")
    for key in kwargs:
        escaped = escaped.replace(f"{{{{{key}}}}}", f"{{{key}}}")
    return escaped.format(**kwargs)


def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    if chunk_size <= 0:
        return [text]
    step = max(1, chunk_size - overlap)
    chunks: List[str] = []
    for start in range(0, len(text), step):
        chunk = text[start : start + chunk_size]
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(text):
            break
    return chunks


def _ensure_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _cache_slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "item"


def _read_cached_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _codex_cache_path(scope: str, paper: Paper, prompt: str) -> Path:
    paper_key = _cache_slug(paper.canonical_id or paper.paper_id or paper.title or "paper")
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return STATE_DIR / "codex_cache" / _cache_slug(scope) / f"{paper_key}-{digest}.json"


async def _run_codex_json_cached(scope: str, paper: Paper, prompt: str) -> Dict[str, Any]:
    cache_path = _codex_cache_path(scope, paper, prompt)
    cached = _read_cached_json(cache_path)
    if cached is not None:
        _log("INFO", f"Codex cache hit for {scope}: {paper.canonical_id}")
        return cached

    payload = await _run_codex_json(prompt)
    try:
        _atomic_write_json(cache_path, payload)
    except Exception as exc:
        _log("WARN", f"Failed to write Codex cache {cache_path}: {exc}")
    return payload


def _get_codex_semaphore() -> anyio.Semaphore:
    global _CODEX_SEMAPHORE
    if _CODEX_SEMAPHORE is None:
        _CODEX_SEMAPHORE = anyio.Semaphore(max(1, CODEX_MAX_CONCURRENCY))
    return _CODEX_SEMAPHORE


async def _run_codex_json(prompt: str) -> Dict[str, Any]:
    semaphore = _get_codex_semaphore()
    async with semaphore:
        return await run_sync(
            codex_cli.run_json,
            prompt=prompt,
            timeout_sec=CODEX_TIMEOUT_SEC,
            cwd=str(BASE_DIR),
            skip_git_repo_check=CODEX_SKIP_GIT_REPO_CHECK,
            use_search=CODEX_USE_SEARCH,
        )


async def codex_process_paper(
    paper: Paper,
    source_text: str,
    source_backend: str = "unknown",
) -> Dict[str, Any]:
    normalized = source_text.strip()
    if not normalized:
        raise RuntimeError("Empty source_text")

    _log(
        "INFO",
        f"Codex processing source text {paper.canonical_id} ({source_backend}, length {len(normalized)} chars)",
    )
    template = _load_prompt(CODEX_PROMPT_PAPER_ANALYSIS_PATH)
    prompt = _render_prompt(
        template,
        title=paper.title,
        authors=", ".join(paper.authors),
        abstract=paper.abstract,
        url=paper.url,
        source_backend=source_backend,
        source_text=normalized,
        source_markdown=normalized,
    )
    try:
        payload = await _run_codex_json_cached("paper_analysis", paper, prompt)
    except Exception as exc:
        raise RuntimeError(
            f"Codex paper analysis failed for {paper.canonical_id} (length {len(normalized)} chars): {exc}"
        ) from exc

    tldr_default = paper.abstract[:400] if paper.abstract else normalized[:400]
    result = {
        "chunk_summaries": _ensure_list(payload.get("chunk_summaries") or payload.get("chunk_summary")),
        "methods_loss": _ensure_list(payload.get("methods_loss")),
        "hyperparams": _ensure_list(payload.get("hyperparams")),
        "evidence_notes": _ensure_list(payload.get("evidence_notes")),
        "github_urls": _dedupe_urls(_ensure_list(payload.get("github_urls"))),
        "primary_github_url": str(payload.get("primary_github_url") or "").strip(),
        "recommendation_score": payload.get("recommendation_score", ""),
        "recommendation_reason": str(payload.get("recommendation_reason") or "").strip(),
        "direction_tags": _ensure_list(payload.get("direction_tags")),
        "tldr": str(payload.get("tldr") or tldr_default),
        "summary": str(payload.get("summary") or tldr_default),
        "email_body_markdown": str(payload.get("email_body_markdown") or "").strip(),
    }
    if not result["email_body_markdown"]:
        result["email_body_markdown"] = _render_email_analysis_markdown(
            paper,
            result["tldr"],
            result["summary"],
            result,
        )
    return result


def _append_markdown_section(lines: List[str], title: str, items: List[str]) -> None:
    if not items:
        return
    lines.append(title)
    for item in items:
        lines.append(f"- {item}")
    lines.append("")


def _default_email_analysis_markdown(tldr: str, summary: str) -> str:
    tldr_text = tldr.strip() or summary.strip() or "No TLDR available."
    summary_text = summary.strip() or tldr_text
    return "\n".join(
        [
            "## Summary",
            f"- {summary_text}",
            f"- TLDR: {tldr_text}",
        ]
    )


def _render_email_analysis_markdown(
    paper: Paper,
    tldr: str,
    summary: str,
    scored_result: Dict[str, Any],
) -> str:
    tldr_text = tldr.strip() or str(scored_result.get("tldr", "")).strip() or summary.strip() or paper.abstract.strip() or "No TLDR available."
    summary_text = summary.strip() or str(scored_result.get("summary", "")).strip() or tldr_text
    recommendation_score = str(scored_result.get("recommendation_score", "")).strip() or "N/A"
    recommendation_reason = str(scored_result.get("recommendation_reason", "")).strip() or "N/A"
    highlights = _ensure_list(scored_result.get("chunk_summaries"))
    evidence_notes = _ensure_list(scored_result.get("evidence_notes"))
    methods_loss = _ensure_list(scored_result.get("methods_loss"))
    hyperparams = _ensure_list(scored_result.get("hyperparams"))
    direction_tags = _ensure_list(scored_result.get("direction_tags"))
    github_urls = _dedupe_urls(_ensure_list(scored_result.get("github_urls")))

    lines = [
        "## Paper",
        f"- Title: {paper.title}",
        f"- Authors: {', '.join(paper.authors) if paper.authors else 'N/A'}",
        "",
        "## Summary",
        f"- {summary_text}",
        f"- TLDR: {tldr_text}",
        "",
        "## Recommendation",
        f"- Score: {recommendation_score}",
        f"- Reason: {recommendation_reason}",
        "",
    ]
    _append_markdown_section(lines, "## Highlights", highlights)
    _append_markdown_section(lines, "## Evidence", evidence_notes)
    _append_markdown_section(lines, "## Methods And Loss", methods_loss)
    _append_markdown_section(lines, "## Hyperparameters", hyperparams)
    _append_markdown_section(lines, "## Direction Tags", direction_tags)
    _append_markdown_section(lines, "## Links", github_urls)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


async def codex_generate_email_analysis(
    paper: Paper,
    clean_text: str,
    tldr: str,
    summary: str,
    scored_result: Optional[Dict[str, Any]] = None,
) -> str:
    _ = clean_text
    if scored_result:
        existing = str(scored_result.get("email_body_markdown") or "").strip()
        if existing:
            return existing
        return _render_email_analysis_markdown(paper, tldr, summary, scored_result)
    return _default_email_analysis_markdown(tldr, summary)

async def save_to_obsidian(
    paper: Paper,
    source_text: str,
    source_path: str,
    source_backend: str,
    codex_result: Dict[str, Any],
    repro_tier: str,
    scanned_repos: List[Dict[str, str]],
) -> None:
    note_path = f"{OBSIDIAN_NOTE_DIR}/{paper.canonical_id}.md"
    recommendation_score = codex_result.get("recommendation_score", "")
    recommendation_reason = codex_result.get("recommendation_reason", "")
    direction_tags = ", ".join(codex_result.get("direction_tags", []))
    tldr = codex_result.get("tldr", "")
    summary = codex_result.get("summary", "")
    methods_loss = "\n".join(
        f"- {s}" for s in codex_result.get("methods_loss", []) if s
    )
    hyperparams = "\n".join(
        f"- {s}" for s in codex_result.get("hyperparams", []) if s
    )
    github_urls = "\n".join(
        f"- {s}" for s in codex_result.get("github_urls", []) if s
    )
    repos_block = "\n".join(
        f"- {r['url']} ({r['tier']})" for r in scanned_repos
    )
    content = "\n".join(
        [
            f"# {paper.title}",
            "",
            f"- Canonical ID: {paper.canonical_id}",
            f"- Raw ID: {paper.paper_id}",
            f"- Authors: {', '.join(paper.authors)}",
            f"- Source Tags: {', '.join(sorted(paper.source_tags))}",
            f"- URL: {paper.url}",
            f"- Source Backend: {source_backend or 'unknown'}",
            f"- Source Path: {source_path or 'N/A'}",
            f"- Reproducibility: {repro_tier}",
            f"- Recommendation Score: {recommendation_score}",
            f"- Recommendation Reason: {recommendation_reason}",
            f"- Direction Tags: {direction_tags}",
            "",
            "## TL;DR",
            tldr,
            "",
            "## Summary",
            summary,
            "",
            "## Methods & Loss",
            methods_loss,
            "",
            "## Hyperparameters",
            hyperparams,
            "",
            "## GitHub URLs",
            github_urls,
            "",
            "## Scanned Repos",
            repos_block,
            "",
            "## Source Text",
            source_text,
        ]
    )

    _log("INFO", f"Writing Obsidian note: {note_path}")
    await run_sync(obsidian_mcp.write_note, path=note_path, content=content)


async def notify(
    paper: Paper,
    tldr: str,
    email_analysis_markdown: str,
    repro_tier: str,
    recommendation_score: Any,
    recommendation_reason: str,
    run_dir: Path,
    prepared_pdf_path: str = "",
) -> None:
    if not EMAIL_RECIPIENTS:
        _log("WARN", "Email recipients not configured; skipping notification.")
        return
    run_dir.mkdir(parents=True, exist_ok=True)
    safe_id = _safe_filename(paper.canonical_id or paper.paper_id or paper.title or "paper")
    pdf_url = _resolve_paper_pdf_url(paper)
    attachments: List[str] = []
    attachment_notice = ""
    prepared_pdf = Path(prepared_pdf_path).expanduser() if prepared_pdf_path else None
    if prepared_pdf is not None and prepared_pdf.exists():
        attachments.append(str(prepared_pdf))
    elif pdf_url:
        attachment_path = run_dir / "attachments" / f"{safe_id}.pdf"
        try:
            downloaded = await run_sync(
                _download_pdf_attachment_sync,
                pdf_url=pdf_url,
                output_path=attachment_path,
            )
            attachments.append(str(downloaded))
        except Exception as exc:
            _log("WARN", f"PDF attachment download failed for {paper.canonical_id}: {exc}")
            attachment_notice = f"PDF attachment download failed; use the original link instead: {pdf_url}"
    else:
        attachment_notice = "No PDF link available, so the email does not include a PDF attachment."

    score_text = str(recommendation_score).strip()
    if not score_text:
        score_text = "N/A"
    elif re.fullmatch(r"\d+(\.\d+)?", score_text):
        score_text = f"{score_text}/10"

    analysis_block = email_analysis_markdown.strip() or _default_email_analysis_markdown(tldr, tldr)
    subject = f"{EMAIL_SUBJECT_PREFIX}{paper.title}"
    body_parts = [
        "## Metadata",
        f"Title: {paper.title}",
        f"Authors: {', '.join(paper.authors)}",
        f"TL;DR: {tldr}",
        f"Recommendation reason: {recommendation_reason or 'N/A'}",
        f"Score: {score_text}",
        f"Reproducibility: {repro_tier}",
        f"Paper URL: {paper.url or 'N/A'}",
        f"PDF URL: {pdf_url or 'N/A'}",
        "",
        "## Codex Analysis",
        analysis_block,
    ]
    if attachment_notice:
        body_parts.extend(["", f"Note: {attachment_notice}"])
    body = "\n".join(body_parts)
    body_path = run_dir / f"email_body_{safe_id}.txt"
    body_path.write_text(body, encoding="utf-8")

    _log("INFO", f"Sending email notification to {len(EMAIL_RECIPIENTS)} recipients")

    def _send_email_via_script() -> None:
        script = BASE_DIR / "scripts" / "send_email_from_body.py"
        if not script.exists():
            raise RuntimeError(f"SMTP script not found: {script}")
        if not CONFIG_PATH:
            raise RuntimeError("Config path not set for SMTP script")
        cmd = [
            sys.executable,
            str(script),
            "--config",
            str(CONFIG_PATH),
            "--subject",
            subject,
            "--body-file",
            str(body_path),
        ]
        if attachments:
            cmd.extend(["--attachments", ";".join(attachments)])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "SMTP send failed")

    try:
        await run_sync(_send_email_via_script)
        return
    except Exception as exc:
        _log("WARN", f"SMTP send failed, falling back to MCP: {exc}")

    await run_sync(
        email_mcp.send_email,
        recipients=EMAIL_RECIPIENTS,
        subject=subject,
        body=body,
        account_name=EMAIL_ACCOUNT_NAME,
        backend="mcp",
        attachments=attachments,
    )


# ------------------
# Main pipeline
# ------------------


def load_seen() -> Set[str]:
    # Deprecated compatibility shim: history dedupe is disabled.
    return set()


def save_seen(seen: Set[str]) -> None:
    # Deprecated compatibility shim: history dedupe is disabled.
    _ = seen


def _is_seen(paper: Paper, seen: Set[str]) -> bool:
    # Deprecated compatibility shim: history dedupe is disabled.
    _ = paper
    _ = seen
    return False


async def _process_paper(
    prepared: PreparedPaper,
    run_dir: Path,
) -> Set[str]:
    paper: Paper = prepared.paper

    if prepared.clean_exception:
        _log(
            "WARN",
            f"Whitelist exception for {paper.canonical_id}, skip scoring: {prepared.clean_exception_reason}",
        )
        tldr = paper.abstract[:400] if paper.abstract else "Whitelisted paper with source-preparation failure."
        codex_result = {
            "chunk_summaries": [],
            "methods_loss": [],
            "hyperparams": [],
            "evidence_notes": [],
            "github_urls": [],
            "primary_github_url": "",
            "recommendation_score": "N/A",
            "recommendation_reason": "author_whitelist_exception_source_failed",
            "direction_tags": ["whitelist-exception"],
            "tldr": tldr,
            "summary": tldr,
            "email_body_markdown": _default_email_analysis_markdown(tldr, tldr),
        }
    else:
        _log("INFO", f"Processing paper: {paper.canonical_id} | {paper.title}")
        codex_result = await codex_process_paper(paper, prepared.source_text, prepared.source_backend)

    repro_tier, scanned_repos = await check_reproducibility(
        paper,
        codex_result.get("github_urls", []),
        codex_result.get("primary_github_url") or "",
    )

    await save_to_obsidian(
        paper,
        prepared.source_text,
        prepared.source_path,
        prepared.source_backend,
        codex_result,
        repro_tier,
        scanned_repos,
    )

    tldr = codex_result.get("tldr", "")
    email_analysis_markdown = await codex_generate_email_analysis(
        paper=paper,
        clean_text=prepared.source_text,
        tldr=tldr,
        summary=str(codex_result.get("summary", "")),
        scored_result=codex_result,
    )
    await notify(
        paper,
        tldr,
        email_analysis_markdown,
        repro_tier,
        codex_result.get("recommendation_score", ""),
        codex_result.get("recommendation_reason", ""),
        run_dir,
        prepared.pdf_path,
    )

    return {paper.canonical_id, paper.paper_id}


async def _prepare_paper(
    paper: Paper,
    whitelist: Set[str],
    super_whitelist: Dict[str, Set[str]],
    stage1_scores: Optional[Dict[str, float]] = None,
) -> Optional[PreparedPaper]:
    whitelisted = author_in_whitelist(paper.authors, whitelist)
    super_hit, super_hit_reasons = super_whitelist_hit(paper, super_whitelist)

    passed_filter, citation_velocity, _ = await passes_filters(paper, whitelist)
    if not passed_filter:
        _log("INFO", f"Filtered out: {paper.canonical_id}")
        return None

    seed_text = _stage1_seed_text(paper)
    stage_components = stage1_scores or compute_stage1_score(seed_text)
    stage1_score = float(stage_components.get("stage1_score", 0.0))
    topic_score = float(stage_components.get("topic_score", 0.0))
    coverage_score = float(stage_components.get("coverage_score", 0.0))
    _log(
        "INFO",
        f"Stage1 (title+abstract) {paper.canonical_id}: score={stage1_score:.3f} "
        f"topic={topic_score:.3f} coverage={coverage_score:.3f} super_hit={super_hit}",
    )

    try:
        mineru_result = await prepare_pdf_markdown(paper)
    except Exception as exc:
        if _is_missing_mineru_key_error(exc):
            raise
        _log("WARN", f"MinerU prepare failed for {paper.canonical_id}, falling back to LaTeX: {exc}")
        return await _prepare_from_latex_fallback(
            paper,
            whitelisted,
            super_hit,
            super_hit_reasons,
            citation_velocity,
            stage1_score,
            topic_score,
            coverage_score,
        )

    status = str(mineru_result.get("status", "")).strip().lower()
    if status == "pending":
        _log("INFO", f"MinerU batch still pending for {paper.canonical_id}: {mineru_result.get('batch_id', '')}")
        return None
    if status != "done":
        _log("WARN", f"MinerU returned status={status or 'unknown'} for {paper.canonical_id}, falling back to LaTeX")
        return await _prepare_from_latex_fallback(
            paper,
            whitelisted,
            super_hit,
            super_hit_reasons,
            citation_velocity,
            stage1_score,
            topic_score,
            coverage_score,
        )

    source_text = str(mineru_result.get("markdown_text") or "")
    source_path = str(mineru_result.get("markdown_path") or "")
    pdf_path = str(mineru_result.get("pdf_path") or "")
    mineru_batch_id = str(mineru_result.get("batch_id") or "")
    if not source_text.strip():
        _log("WARN", f"MinerU markdown empty for {paper.canonical_id}, falling back to LaTeX")
        return await _prepare_from_latex_fallback(
            paper,
            whitelisted,
            super_hit,
            super_hit_reasons,
            citation_velocity,
            stage1_score,
            topic_score,
            coverage_score,
        )

    return PreparedPaper(
        paper=paper,
        whitelisted=whitelisted,
        super_whitelist_hit=super_hit,
        super_whitelist_hit_reasons=super_hit_reasons,
        citation_velocity=citation_velocity,
        source_text=source_text,
        source_path=source_path,
        source_backend="mineru_markdown",
        pdf_path=pdf_path,
        mineru_batch_id=mineru_batch_id,
        stage1_score=stage1_score,
        topic_score=topic_score,
        coverage_score=coverage_score,
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    _atomic_write_text(path, f"{rendered}\n")


def _write_latest_run_pointers(run_dir: Path, payload: Dict[str, Any]) -> None:
    out_dir = run_dir.parent
    resolved_run_dir = run_dir.resolve()
    _atomic_write_text(out_dir / "latest_run.txt", f"{resolved_run_dir}\n")
    _atomic_write_json(out_dir / "latest_run.json", payload)


def _write_run_summary(run_dir: Path, payload: Dict[str, Any]) -> None:
    _atomic_write_json(run_dir / "run_summary.json", payload)


async def run_pipeline(date_window: Optional[DateWindow] = None) -> None:
    window = date_window or ACTIVE_DATE_WINDOW or _resolve_date_window(None, None, None)

    start_ts = time.monotonic()
    started_at = datetime.now(CST_TZ)
    run_id = started_at.strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_ROOT / "out" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _log("INFO", f"Run directory: {run_dir.resolve()}")

    base_payload: Dict[str, Any] = {
        "run_id": run_id,
        "run_dir": str(run_dir.resolve()),
        "start_date": window.start_date.isoformat(),
        "end_date": window.end_date.isoformat(),
        "started_at_cst": started_at.isoformat(),
        "finished_at_cst": "",
        "status": "running",
        "error": "",
        "log_file": str(LOG_FILE_PATH.resolve()) if LOG_FILE_PATH else "",
    }
    try:
        _write_latest_run_pointers(run_dir, base_payload)
        _write_run_summary(run_dir, base_payload)
    except Exception as exc:
        _log("WARN", f"Failed to write run pointers: {exc}")

    candidates: List[Paper] = []
    shortlist_count: Optional[int] = None
    processed_ids: Set[str] = set()
    pipeline_error = ""
    try:
        whitelist = load_whitelist(WHITELIST_PATH)
        super_whitelist = load_super_whitelist(SUPER_WHITELIST_PATH)

        _log(
            "INFO",
            f"Pipeline start. Date window (CST): {window.start_date.isoformat()} ~ {window.end_date.isoformat()}",
        )
        candidates = await discover_papers(window)
        _log("INFO", f"Total discovered candidates: {len(candidates)}")
        _log(
            "INFO",
            "History sent-paper dedupe disabled; previously sent papers may be notified again.",
        )

        stage1_entries: List[Dict[str, Any]] = []
        stage1_scores: Dict[str, Dict[str, float]] = {}
        for paper in candidates:
            seed_text = _stage1_seed_text(paper)
            scores = compute_stage1_score(seed_text)
            key = paper.canonical_id or paper.paper_id
            stage1_scores[key] = scores
            stage1_entries.append(
                {
                    "paper": paper,
                    "stage1_score": scores["stage1_score"],
                    "topic_score": scores["topic_score"],
                    "coverage_score": scores["coverage_score"],
                }
            )

        _log("INFO", "Stage1 prefilter based on title+abstract.")
        prefiltered_entries = apply_stage1_prefilter(stage1_entries)
        prefiltered: List[Paper] = []
        prefiltered_ids: Set[str] = set()
        for entry in prefiltered_entries:
            paper = entry["paper"]
            key = paper.canonical_id or paper.paper_id
            if key in prefiltered_ids:
                continue
            prefiltered_ids.add(key)
            prefiltered.append(paper)

        for paper in candidates:
            key = paper.canonical_id or paper.paper_id
            if key in prefiltered_ids:
                continue
            if author_in_whitelist(paper.authors, whitelist):
                prefiltered_ids.add(key)
                prefiltered.append(paper)
                continue
            super_hit, _ = super_whitelist_hit(paper, super_whitelist)
            if super_hit:
                prefiltered_ids.add(key)
                prefiltered.append(paper)

        shortlist_count = len(prefiltered)
        _log("INFO", f"Candidates after Stage1 (title+abstract): {shortlist_count}")

        prepared: List[PreparedPaper] = []
        prepare_lock = anyio.Lock()
        prepare_semaphore = anyio.Semaphore(max(1, PAPER_EVAL_CONCURRENCY))
        fatal_prepare_error: Optional[BaseException] = None

        async def _prepare_worker(paper: Paper) -> None:
            nonlocal fatal_prepare_error
            async with prepare_semaphore:
                try:
                    key = paper.canonical_id or paper.paper_id
                    scores = stage1_scores.get(key)
                    item = await _prepare_paper(
                        paper,
                        whitelist,
                        super_whitelist,
                        stage1_scores=scores,
                    )
                except Exception as exc:
                    if _is_missing_mineru_key_error(exc):
                        _log("ERROR", f"Fatal MinerU configuration error for {paper.canonical_id}: {exc}")
                        fatal_prepare_error = exc
                        return
                    _log("ERROR", f"Unexpected prepare failure for {paper.canonical_id}: {exc}")
                    item = None
                if item is not None:
                    async with prepare_lock:
                        prepared.append(item)

        async with anyio.create_task_group() as tg:
            for paper in prefiltered:
                tg.start_soon(_prepare_worker, paper)

        if fatal_prepare_error is not None:
            raise fatal_prepare_error

        whitelist_exceptions = [item for item in prepared if item.clean_exception]
        if whitelist_exceptions:
            _log("INFO", f"Whitelist clean-failure exceptions: {len(whitelist_exceptions)}")
        shortlist = prepared
        _log("INFO", f"Prepared papers after prefilter: {len(shortlist)}")

        lock = anyio.Lock()
        semaphore = anyio.Semaphore(max(1, PAPER_EVAL_CONCURRENCY))

        async def _worker(item: PreparedPaper) -> None:
            async with semaphore:
                try:
                    ids = await _process_paper(item, run_dir)
                except Exception as exc:
                    _log("ERROR", f"Unexpected per-paper failure: {exc}")
                    ids = set()
                if ids:
                    async with lock:
                        processed_ids.update(ids)

        async with anyio.create_task_group() as tg:
            for item in shortlist:
                tg.start_soon(_worker, item)

        _log(
            "INFO",
            f"Pipeline finished in {time.monotonic() - start_ts:.1f}s, processed={len(processed_ids)} ids",
        )
    except Exception as exc:
        pipeline_error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        finished_at = datetime.now(CST_TZ)
        elapsed_sec = time.monotonic() - start_ts
        final_payload = dict(base_payload)
        final_payload.update(
            {
                "finished_at_cst": finished_at.isoformat(),
                "status": "error" if pipeline_error else "ok",
                "error": pipeline_error,
                "elapsed_sec": round(elapsed_sec, 3),
                "discovered_count": len(candidates),
                "shortlist_count": shortlist_count,
                "processed_count": len(processed_ids),
            }
        )
        try:
            _write_run_summary(run_dir, final_payload)
            _write_latest_run_pointers(run_dir, final_payload)
        except Exception as exc:
            _log("WARN", f"Failed to write run summary/pointers: {exc}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Config path. Priority: --config > AIRESEARCH_CONFIG > config.local.yaml > config.example.yaml",
    )
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument(
        "--force-run",
        action="store_true",
        help="Run even if already ran today (CST).",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=None,
        help="Relative window (inclusive days, CST). Ignored when --start-date/--end-date are both provided.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Inclusive start date, format YYYY-MM-DD (CST). Must pair with --end-date.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Inclusive end date, format YYYY-MM-DD (CST). Must pair with --start-date.",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Optional log file path. When set, logs are appended to this file (UTF-8).",
    )
    args = parser.parse_args()

    global CONFIG_PATH
    global CONFIG_BASE_DIR
    global ACTIVE_DATE_WINDOW
    CONFIG_PATH = resolve_config_path(args.config)
    CONFIG_BASE_DIR = CONFIG_PATH.parent if CONFIG_PATH else REPO_ROOT
    configure_logging(args.log_file)
    _log("INFO", f"Using config: {CONFIG_PATH}")
    try:
        config = load_config(CONFIG_PATH) if CONFIG_PATH else {}
    except Exception as exc:
        _log_exception("Failed to load config", exc)
        return
    try:
        apply_config(config)
    except Exception as exc:
        _log_exception("Failed to apply config", exc)
        return

    try:
        ACTIVE_DATE_WINDOW = _resolve_date_window(args.days_back, args.start_date, args.end_date)
    except ValueError as exc:
        _log("ERROR", f"Invalid date window args: {exc}")
        return
    _log(
        "INFO",
        "Effective date window (CST): "
        f"{ACTIVE_DATE_WINDOW.start_date.isoformat()} ~ {ACTIVE_DATE_WINDOW.end_date.isoformat()} "
        f"({_window_days(ACTIVE_DATE_WINDOW)} days)",
    )

    today_cst = _cst_today_str()
    if args.run_once:
        last_run = load_last_run(LAST_RUN_PATH)
        if last_run == today_cst and not args.force_run:
            _log("INFO", f"Already ran today (CST): {today_cst}. Exiting.")
            return

    async def _runner() -> None:
        await run_pipeline(ACTIVE_DATE_WINDOW)

    try:
        anyio.run(_runner)
    except Exception as exc:
        _log_exception("Pipeline failed", exc)
        return

    if args.run_once:
        save_last_run(LAST_RUN_PATH, today_cst)
        _log("INFO", f"Saved last_run: {today_cst}")


if __name__ == "__main__":
    main()
