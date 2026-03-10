from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from typing import Dict, List

from ..compatibility import resolve_mcp_config_path


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return default


def _get_recipients(value: List[str] | str) -> List[str]:
    if isinstance(value, list):
        return [v for v in value if v]
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",")]
        return [p for p in parts if p]
    return []


def _get_email_backend(explicit: str | None = None) -> str:
    if explicit:
        return explicit.strip().lower()
    return os.environ.get("EMAIL_BACKEND", "auto").strip().lower()


def _get_account_name(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    return os.environ.get("EMAIL_ACCOUNT_NAME", "").strip()


def _get_mcp_email_server() -> tuple[str, list[str]]:
    command = os.environ.get("MCP_EMAIL_COMMAND", "").strip()
    args_env = os.environ.get("MCP_EMAIL_ARGS", "").strip()
    if command:
        args = [a for a in args_env.split() if a] if args_env else ["stdio"]
        return command, args

    config_path = resolve_mcp_config_path()
    if not config_path.exists():
        raise RuntimeError(f"MCP config not found: {config_path}")

    data = json.loads(config_path.read_text(encoding="utf-8"))
    server = data.get("mcpServers", {}).get("email", {})
    if not isinstance(server, dict):
        raise RuntimeError(f"{config_path.name} missing mcpServers.email config")

    command = str(server.get("command", "")).strip()
    args = server.get("args") or []
    if not command:
        raise RuntimeError(f"{config_path.name} mcpServers.email.command is empty")

    return command, [str(a) for a in args]


def _send_email_via_mcp(
    recipients: List[str] | str,
    subject: str,
    body: str,
    account_name: str | None = None,
    cc: List[str] | str | None = None,
    bcc: List[str] | str | None = None,
    html: bool | None = None,
    attachments: List[str] | None = None,
) -> Dict[str, object]:
    account = _get_account_name(account_name)
    if not account:
        raise RuntimeError("EMAIL_ACCOUNT_NAME is required for MCP email")

    to_list = _get_recipients(recipients)
    if not to_list:
        raise RuntimeError("Recipients list is empty")

    cmd, args = _get_mcp_email_server()
    payload: Dict[str, object] = {
        "account_name": account,
        "recipients": to_list,
        "subject": subject,
        "body": body,
    }
    if cc:
        payload["cc"] = _get_recipients(cc)
    if bcc:
        payload["bcc"] = _get_recipients(bcc)
    if html is not None:
        payload["html"] = bool(html)
    if attachments:
        payload["attachments"] = attachments

    async def _run() -> Dict[str, object]:
        import anyio
        import mcp
        from mcp import ClientSession, StdioServerParameters

        server = StdioServerParameters(command=cmd, args=args, env=None, cwd=None)
        async with mcp.stdio_client(server) as (read_stream, write_stream):
            session = ClientSession(read_stream, write_stream)
            await session.initialize()
            result = await session.call_tool("send_email", payload)
            if result.isError:
                raise RuntimeError(f"MCP send_email failed: {result.content}")
            return result.structuredContent or {"ok": True, "backend": "mcp"}

    import anyio

    return anyio.run(_run)


def send_email(
    recipients: List[str] | str,
    subject: str,
    body: str,
    from_email: str | None = None,
    account_name: str | None = None,
    backend: str | None = None,
    attachments: List[str] | None = None,
) -> Dict[str, object]:
    """Send an email via SMTP."""
    chosen_backend = _get_email_backend(backend)
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    use_tls = _get_bool("SMTP_USE_TLS", True)
    use_ssl = _get_bool("SMTP_USE_SSL", False)

    if chosen_backend in ("mcp", "qq_sender", "qq-sender", "qqsender"):
        return _send_email_via_mcp(
            recipients,
            subject,
            body,
            account_name=account_name,
            attachments=attachments,
        )
    if chosen_backend == "auto" and not host:
        return _send_email_via_mcp(
            recipients,
            subject,
            body,
            account_name=account_name,
            attachments=attachments,
        )
    if chosen_backend not in ("smtp", "auto"):
        raise RuntimeError(f"Unknown EMAIL_BACKEND: {chosen_backend}")

    to_list = _get_recipients(recipients)
    if not to_list:
        raise RuntimeError("Recipients list is empty")

    sender = from_email or os.environ.get("SMTP_FROM", "").strip() or user
    if not sender:
        raise RuntimeError("SMTP_FROM or SMTP_USER is required")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)
    msg.set_content(body)

    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)

    try:
        if use_tls and not use_ssl:
            server.starttls()
        if user and password:
            server.login(user, password)
        server.send_message(msg)
    finally:
        server.quit()

    return {"ok": True, "recipients": to_list}

