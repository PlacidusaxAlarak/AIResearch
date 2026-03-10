from __future__ import annotations

import os
import ssl
from email.message import EmailMessage
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]


def _load_codex_smtp_env(account_name: str | None = None):
    user_profile = os.environ.get("USERPROFILE")
    if not user_profile:
        return None
    cfg_path = Path(user_profile) / ".codex" / "config.toml"
    if not cfg_path.exists():
        return None
    data = tomllib.loads(cfg_path.read_text(encoding="utf-8-sig"))
    servers = data.get("mcp_servers", {}) or {}
    key = account_name or "qq-sender"
    server = servers.get(key)
    if not server:
        return None
    env = server.get("env", {}) or {}
    if isinstance(env, list):
        env_dict = {}
        for item in env:
            if isinstance(item, dict):
                k = item.get("key") or item.get("name")
                v = item.get("value")
                if k:
                    env_dict[k] = v
        env = env_dict
    return env


def _smtp_from_env(config: dict | None):
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    host = os.environ.get("SMTP_HOST")
    port = os.environ.get("SMTP_PORT")
    ssl_flag = os.environ.get("SMTP_SSL")

    if user and password and host and port:
        return {
            "user": user,
            "password": password,
            "host": host,
            "port": int(port),
            "ssl": str(ssl_flag or "true").lower() in ("1", "true", "yes"),
        }

    email_cfg = (config or {}).get("email")
    account = "qq-sender"
    if isinstance(email_cfg, dict):
        account = email_cfg.get("smtp_account") or account

    env = _load_codex_smtp_env(account)
    if not env:
        return None

    user = env.get("MCP_EMAIL_SERVER_USER_NAME") or env.get(
        "MCP_EMAIL_SERVER_EMAIL_ADDRESS"
    )
    password = env.get("MCP_EMAIL_SERVER_PASSWORD")
    host = env.get("MCP_EMAIL_SERVER_SMTP_HOST", "smtp.qq.com")
    port = int(env.get("MCP_EMAIL_SERVER_SMTP_PORT", 465))
    ssl_flag = str(env.get("MCP_EMAIL_SERVER_SMTP_SSL", "true")).lower() in (
        "1",
        "true",
        "yes",
    )

    if not user or not password:
        return None
    return {"user": user, "password": password, "host": host, "port": port, "ssl": ssl_flag}


def _guess_mime(path: Path):
    suffix = path.suffix.lower()
    if suffix in (".txt", ".log"):
        return ("text", "plain")
    if suffix == ".json":
        return ("application", "json")
    if suffix == ".zip":
        return ("application", "zip")
    if suffix == ".pdf":
        return ("application", "pdf")
    return ("application", "octet-stream")


def send_smtp_email(config, subject, body, recipients, attachment_paths, logger):
    smtp_cfg = _smtp_from_env(config)
    if not smtp_cfg:
        raise RuntimeError("SMTP credentials not found (env or Codex config).")

    timeout = int((config or {}).get("email", {}).get("smtp_timeout_seconds", 180))

    msg = EmailMessage()
    msg["From"] = smtp_cfg["user"]
    msg["To"] = ", ".join(recipients or [])
    msg["Subject"] = subject
    msg.set_content(body or "")

    for path in attachment_paths or []:
        p = Path(path)
        if not p.exists():
            if logger:
                logger.warning("Attachment missing: %s", p)
            continue
        maintype, subtype = _guess_mime(p)
        msg.add_attachment(
            p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name
        )

    context = ssl.create_default_context()
    if smtp_cfg["ssl"]:
        with _smtp_ssl(smtp_cfg, context, timeout) as s:
            s.send_message(msg)
    else:
        with _smtp_plain(smtp_cfg, context, timeout) as s:
            s.send_message(msg)


def _smtp_ssl(cfg, context, timeout):
    import smtplib

    s = smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=timeout)
    s.login(cfg["user"], cfg["password"])
    return s


def _smtp_plain(cfg, context, timeout):
    import smtplib

    s = smtplib.SMTP(cfg["host"], cfg["port"], timeout=timeout)
    s.ehlo()
    s.starttls(context=context)
    s.login(cfg["user"], cfg["password"])
    return s

