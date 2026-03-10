from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from airesearch.core import smtp_send


def _get_recipients(value: List[str] | str | None) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [v for v in value if v]
    parts = [p.strip() for p in str(value).replace(";", ",").split(",")]
    return [p for p in parts if p]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True)
    parser.add_argument("--subject", type=str, required=True)
    parser.add_argument("--body-file", type=str, required=True)
    parser.add_argument("--recipients", type=str, default="")
    parser.add_argument("--attachments", type=str, default="")
    args = parser.parse_args()

    config_path = Path(args.config)
    config: Dict[str, Any] = {}
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            config = data
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("send-email")

    recipients = _get_recipients(args.recipients)
    if not recipients:
        email_cfg = config.get("email") if isinstance(config.get("email"), dict) else {}
        recipients = _get_recipients(email_cfg.get("recipients"))
    if not recipients:
        recipients = _get_recipients(config.get("email_recipients"))
    if not recipients:
        raise SystemExit("email recipients missing in config")

    body_path = Path(args.body_file)
    body = body_path.read_text(encoding="utf-8", errors="replace")

    attachments = []
    if args.attachments:
        for part in args.attachments.replace(",", ";").split(";"):
            path = part.strip()
            if path:
                attachments.append(path)

    smtp_send.send_smtp_email(config, args.subject, body, recipients, attachments, logger)


if __name__ == "__main__":
    main()
