"""Deliver the rendered digest. Local HTML file always happens (zero config,
always works); email/Slack are optional on top of it if creds are set.

Two email transports are supported:
- Resend (HTTP API): works from any environment with HTTPS egress, including
  network-sandboxed cloud environments that block raw TCP (SMTP needs a raw
  socket; Resend is just a POST request). Takes priority if RESEND_API_KEY
  is set.
- SMTP: the traditional path, for environments with normal unrestricted
  internet access (e.g. your own machine via the cron/launchd scheduler).

Both support attachments (e.g. tailored resume PDFs), read from disk and
base64-encoded entirely in this process — no external service ever needs to
inspect this code to send a file.
"""
from __future__ import annotations

import base64
import logging
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


def write_html_file(html: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    return output_path


def send_email(
    html: str,
    subject: str,
    attachments: list[Path] | None = None,
) -> bool:
    """Sends the digest email via Resend (preferred, HTTPS-only) or SMTP.

    Returns False (no-op) if neither transport is configured.
    DIGEST_EMAIL_TO may be a single address or a comma-separated list.
    """
    to_raw = os.environ.get("DIGEST_EMAIL_TO")
    if not to_raw:
        logger.info("DIGEST_EMAIL_TO not set, skipping email delivery.")
        return False
    to_addrs = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key:
        return _send_via_resend(html, subject, to_addrs, resend_key, attachments)

    host = os.environ.get("SMTP_HOST")
    from_addr = os.environ.get("DIGEST_EMAIL_FROM") or os.environ.get("SMTP_USER")
    if not (host and from_addr):
        logger.info("Neither RESEND_API_KEY nor SMTP_HOST configured, skipping email delivery.")
        return False
    return _send_via_smtp(html, subject, to_addrs, host, from_addr, attachments)


def _send_via_resend(
    html: str,
    subject: str,
    to_addrs: list[str],
    api_key: str,
    attachments: list[Path] | None,
) -> bool:
    from_addr = os.environ.get("RESEND_FROM", "onboarding@resend.dev")
    payload = {"from": from_addr, "to": to_addrs, "subject": subject, "html": html}

    if attachments:
        payload["attachments"] = [
            {
                "filename": Path(p).name,
                "content": base64.b64encode(Path(p).read_bytes()).decode(),
            }
            for p in attachments
        ]

    resp = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    logger.info("Sent digest email via Resend to %s", ", ".join(to_addrs))
    return True


def _send_via_smtp(
    html: str,
    subject: str,
    to_addrs: list[str],
    host: str,
    from_addr: str,
    attachments: list[Path] | None,
) -> bool:
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)

    for p in attachments or []:
        p = Path(p)
        part = MIMEApplication(p.read_bytes(), Name=p.name)
        part["Content-Disposition"] = f'attachment; filename="{p.name}"'
        msg.attach(part)

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        if user and password:
            server.login(user, password)
        # sendmail's recipient list must be individual addresses, not a
        # single comma-joined string, or the envelope RCPT TO is malformed.
        server.sendmail(from_addr, to_addrs, msg.as_string())

    logger.info("Sent digest email via SMTP to %s", ", ".join(to_addrs))
    return True


def send_slack(entries, run_date: str) -> bool:
    """Posts a summary to Slack via incoming webhook if SLACK_WEBHOOK_URL is set."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.info("Slack webhook not configured, skipping Slack delivery.")
        return False

    lines = [f"*Job Digest — {run_date}* ({len(entries)} matches)"]
    for e in entries:
        lines.append(f"• [{e.llm_fit_score}/100] <{e.url}|{e.title} @ {e.company}> ({e.source})")

    resp = requests.post(webhook_url, json={"text": "\n".join(lines)}, timeout=15)
    resp.raise_for_status()
    logger.info("Posted digest to Slack.")
    return True
