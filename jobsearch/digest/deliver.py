"""Deliver the rendered digest. Local HTML file always happens (zero config,
always works); email/Slack are optional on top of it if creds are set.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


def write_html_file(html: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    return output_path


def send_email(html: str, subject: str) -> bool:
    """Sends via SMTP if all required env vars are set. Returns False (no-op) otherwise.

    DIGEST_EMAIL_TO may be a single address or a comma-separated list.
    """
    host = os.environ.get("SMTP_HOST")
    to_raw = os.environ.get("DIGEST_EMAIL_TO")
    from_addr = os.environ.get("DIGEST_EMAIL_FROM") or os.environ.get("SMTP_USER")
    if not (host and to_raw and from_addr):
        logger.info("SMTP not configured, skipping email delivery.")
        return False

    to_addrs = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        if user and password:
            server.login(user, password)
        # sendmail's recipient list must be individual addresses, not a
        # single comma-joined string, or the envelope RCPT TO is malformed.
        server.sendmail(from_addr, to_addrs, msg.as_string())

    logger.info("Sent digest email to %s", ", ".join(to_addrs))
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
