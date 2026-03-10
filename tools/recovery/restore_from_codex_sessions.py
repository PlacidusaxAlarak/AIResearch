#!/usr/bin/env python3
"""Recover deleted files in a workspace from Codex session logs.

This script scans Codex session JSONL files for shell commands that used
Get-Content on known project files, then writes the best matching output
back to the workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

WORKSPACE = Path(__file__).resolve().parents[2]
_USER_PROFILE = Path(os.environ.get("USERPROFILE", str(Path.home())))
SESSION_ROOTS = [
    _USER_PROFILE / ".codex" / "sessions",
    _USER_PROFILE / ".codex" / "archived_sessions",
]

TARGET_FILES = [
    ".env.example",
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "config.local.yaml",
    "config.example.yaml",
    "mcp.local.json",
    "mcp.example.json",
    "orchestrator.py",
    "arxiv_mcp.py",
    "hf_papers_mcp.py",
    "github_mcp.py",
    "email_mcp.py",
    "fetch_mcp.py",
    "scholarly_mcp.py",
    "obsidian_mcp.py",
    "latex_reader.py",
    "magic_pdf_mcp.py",
    "smtp_send.py",
    "codex_cli.py",
    "scripts/windows/run_daily_recommendation.cmd",
    "scripts/windows/run_orchestrator_date_range.cmd",
    "configs/config_hpc_codegen_6m.yaml",
    "configs/config_test_2402.yaml",
    "configs/whitelist_authors.yaml",
    "configs/super_whitelist.yaml",
    "docs/seen_papers.md",
    "scripts/send_email_from_body.py",
    "ops/check_startup.ps1",
    "ops/rename_project_folder.ps1",
    "ops/run_super_whitelist_service.ps1",
    "ops/run_with_date_range.ps1",
    "ops/setup_startup.ps1",
    "ops/setup_task.ps1",
    "tests/test_mcp_arxiv_characterization.py",
    "tests/test_mcp_github_scholarly_obsidian_email_characterization.py",
    "tests/test_mcp_hf_characterization.py",
    "tests/test_orchestrator_cli_characterization.py",
    "tests/test_orchestrator_filters_characterization.py",
    "tests/test_orchestrator_state_characterization.py",
]


@dataclass
class CallRecord:
    call_id: str
    command: str
    session_file: Path
    timestamp: str


@dataclass
class OutputRecord:
    call_id: str
    output: str
    session_file: Path
    timestamp: str


@dataclass
class Candidate:
    target: str
    score: int
    content: str
    command: str
    session_file: Path
    call_id: str


def _iter_jsonl_files() -> Iterable[Path]:
    for root in SESSION_ROOTS:
        if not root.exists():
            continue
        if root.is_file() and root.suffix == ".jsonl":
            yield root
            continue
        for path in root.rglob("*.jsonl"):
            yield path


def _parse_command(arguments: object) -> str:
    if isinstance(arguments, dict):
        value = arguments.get("command")
        return value if isinstance(value, str) else ""
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                value = parsed.get("command")
                return value if isinstance(value, str) else ""
        except json.JSONDecodeError:
            pass
        return arguments
    return ""


def _collect_calls_and_outputs(
    jsonl_files: Iterable[Path],
) -> Tuple[Dict[str, CallRecord], Dict[str, List[OutputRecord]]]:
    calls: Dict[str, CallRecord] = {}
    outputs: Dict[str, List[OutputRecord]] = {}

    for path in jsonl_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        entry = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") != "response_item":
                        continue

                    payload = entry.get("payload")
                    if not isinstance(payload, dict):
                        continue

                    ptype = payload.get("type")
                    call_id = payload.get("call_id")
                    timestamp = entry.get("timestamp", "")

                    if ptype == "function_call" and payload.get("name") == "shell_command":
                        if not isinstance(call_id, str):
                            continue
                        command = _parse_command(payload.get("arguments"))
                        if not command:
                            continue
                        calls[call_id] = CallRecord(
                            call_id=call_id,
                            command=command,
                            session_file=path,
                            timestamp=timestamp,
                        )

                    if ptype == "function_call_output":
                        if not isinstance(call_id, str):
                            continue
                        output_text = payload.get("output")
                        if not isinstance(output_text, str):
                            continue
                        outputs.setdefault(call_id, []).append(
                            OutputRecord(
                                call_id=call_id,
                                output=output_text,
                                session_file=path,
                                timestamp=timestamp,
                            )
                        )
        except OSError:
            continue

    return calls, outputs


def _command_mentions_target(command: str, target: str) -> bool:
    lc = command.lower().replace("\\", "/")
    base = Path(target).name.lower()
    target_lc = target.lower().replace("\\", "/")

    if "get-content" not in lc:
        return False
    if "| py -3 -" in lc or "| python -" in lc:
        return False

    segments = re.split(r"[;\n]+", lc)
    for segment in segments:
        if "get-content" not in segment:
            continue
        gc_index = segment.find("get-content")
        tail = segment[gc_index:]
        if base in tail or target_lc in tail:
            return True
    return False


def _extract_output_payload(output_text: str) -> str:
    marker_match = re.search(r"Output:\r?\n", output_text)
    if marker_match:
        payload = output_text[marker_match.end() :]
    else:
        payload = output_text

    profile_markers = [
        ". : 无法加载文件 C:\\Users\\Hutao\\Documents\\WindowsPowerShell\\profile.ps1",
        ". : File C:\\Users\\Hutao\\Documents\\WindowsPowerShell\\profile.ps1",
    ]
    for marker in profile_markers:
        idx = payload.find(marker)
        if idx != -1:
            payload = payload[:idx].rstrip("\r\n")
            break
    return payload


def _strip_line_numbers_if_needed(text: str) -> str:
    lines = text.splitlines()
    nonempty = [line for line in lines if line.strip()]
    if len(nonempty) < 5:
        return text

    sample = nonempty[: min(120, len(nonempty))]
    numbered = sum(bool(re.match(r"^\s*\d+\s*:\s", line)) for line in sample)
    if numbered < max(4, int(len(sample) * 0.70)):
        return text

    stripped_lines = [re.sub(r"^\s*\d+\s*:\s?", "", line) for line in lines]
    stripped = "\n".join(stripped_lines)
    if text.endswith("\n") or text.endswith("\r\n"):
        stripped += "\n"
    return stripped


def _score_candidate(command: str, content: str, target: str) -> int:
    lc = command.lower()
    score = 0

    if "get-content" not in lc:
        return -10_000

    score += 20
    if "-raw" in lc:
        score += 220
    if "-encoding utf8" in lc or "-encoding utf-8" in lc:
        score += 200
    if "select-object" not in lc and "foreach-object" not in lc:
        score += 120
    if "foreach-object" in lc and ("{0,4}" in lc or "{0,5}" in lc or "{0,4}:" in lc):
        score += 160

    if "select-object" in lc:
        score -= 200
    if "-skip" in lc:
        score -= 260
    if "-first" in lc or "-last" in lc or "-totalcount" in lc:
        score -= 240
    if "if (test-path" in lc:
        score -= 180
    if ";" in lc:
        score -= 90

    content_lc = content.lower()
    if "tokens truncated" in content_lc:
        return -10_000
    if "not found" in content_lc and len(content_lc) < 400:
        score -= 260
    if len(content) < 30:
        score -= 220

    suffix = Path(target).suffix.lower()
    head = content[:1200]
    if suffix == ".py" and ("def " in head or "import " in head):
        score += 60
    if suffix in {".yaml", ".yml"} and ":" in head:
        score += 40
    if suffix == ".md" and ("\n#" in head or head.startswith("#")):
        score += 40
    if suffix == ".cmd" and ("python" in head.lower() or "@echo" in head.lower()):
        score += 40
    if suffix == ".json" and ("{" in head or "[" in head):
        score += 40

    score += min(len(content), 250_000) // 800
    return score


def _accept_candidate(target: str, score: int) -> bool:
    suffix = Path(target).suffix.lower()
    threshold = 80
    if suffix == ".py":
        threshold = 120
    elif suffix in {".yaml", ".yml", ".json", ".md", ".cmd"}:
        threshold = 100
    elif suffix == ".ps1":
        threshold = 80
    elif target in {".gitignore", ".env.example"}:
        threshold = 70
    return score >= threshold


def _normalize_content(output_text: str) -> str:
    payload = _extract_output_payload(output_text)
    payload = _strip_line_numbers_if_needed(payload)
    # Remove a single trailing command artifact block if present.
    payload = re.sub(r"\r?\n所在位置 行:\d+ 字符:.*\Z", "", payload, flags=re.S)
    return payload


def _find_best_candidate_for_target(
    target: str,
    calls: Dict[str, CallRecord],
    outputs: Dict[str, List[OutputRecord]],
) -> Optional[Candidate]:
    best: Optional[Candidate] = None

    for call_id, call in calls.items():
        if not _command_mentions_target(call.command, target):
            continue
        out_list = outputs.get(call_id, [])
        if not out_list:
            continue

        for out in out_list:
            content = _normalize_content(out.output)
            if not content.strip():
                continue
            score = _score_candidate(call.command, content, target)
            cand = Candidate(
                target=target,
                score=score,
                content=content,
                command=call.command,
                session_file=out.session_file,
                call_id=call_id,
            )
            if best is None:
                best = cand
                continue
            if cand.score > best.score:
                best = cand
            elif cand.score == best.score and len(cand.content) > len(best.content):
                best = cand
    return best


def _write_recovered_file(target: str, content: str) -> None:
    out_path = WORKSPACE / target
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover project files from Codex session JSONL logs."
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=str(WORKSPACE),
        help="Workspace root where recovered files will be written.",
    )
    parser.add_argument(
        "--session-root",
        action="append",
        default=[],
        help="Session log root. Can be provided multiple times.",
    )
    return parser.parse_args()


def main() -> int:
    global WORKSPACE
    global SESSION_ROOTS

    args = _parse_args()
    WORKSPACE = Path(args.workspace).expanduser().resolve()
    if args.session_root:
        SESSION_ROOTS = [Path(v).expanduser().resolve() for v in args.session_root]

    jsonl_files = list(_iter_jsonl_files())
    calls, outputs = _collect_calls_and_outputs(jsonl_files)

    recovered: List[Candidate] = []
    missing: List[str] = []
    report_rows: List[Dict[str, object]] = []

    for target in TARGET_FILES:
        best = _find_best_candidate_for_target(target, calls, outputs)
        if best is None or not _accept_candidate(target, best.score):
            missing.append(target)
            continue
        _write_recovered_file(target, best.content)
        recovered.append(best)
        report_rows.append(
            {
                "target": target,
                "score": best.score,
                "bytes": len(best.content.encode("utf-8")),
                "call_id": best.call_id,
                "session_file": str(best.session_file),
                "command": best.command,
            }
        )

    report = {
        "jsonl_files_scanned": len(jsonl_files),
        "call_records": len(calls),
        "output_records": sum(len(v) for v in outputs.values()),
        "recovered_count": len(recovered),
        "missing_count": len(missing),
        "missing": missing,
        "recovered": report_rows,
    }
    report_path = WORKSPACE / "tools" / "recovery" / "recovery_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Scanned JSONL files: {len(jsonl_files)}")
    print(f"Recovered files: {len(recovered)}")
    print(f"Missing files: {len(missing)}")
    if missing:
        print("Missing:")
        for item in missing:
            print(f"  - {item}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
