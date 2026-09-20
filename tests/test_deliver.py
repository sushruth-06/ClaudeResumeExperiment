from __future__ import annotations

import base64

from jobsearch.digest import deliver


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.starttls_called = False
        self.login_args = None
        self.sendmail_args = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, user, password):
        self.login_args = (user, password)

    def sendmail(self, from_addr, to_addrs, msg):
        self.sendmail_args = (from_addr, to_addrs, msg)


def setup_function(_):
    FakeSMTP.instances.clear()


def _clear_resend(monkeypatch):
    # The real .env carries a live RESEND_API_KEY for this project; SMTP-path
    # tests must explicitly disable it so they exercise SMTP deterministically.
    monkeypatch.delenv("RESEND_API_KEY", raising=False)


def test_send_email_splits_comma_separated_recipients(monkeypatch):
    _clear_resend(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("DIGEST_EMAIL_TO", "a@example.com, b@example.com")
    monkeypatch.setenv("DIGEST_EMAIL_FROM", "sender@example.com")
    monkeypatch.setattr(deliver.smtplib, "SMTP", FakeSMTP)

    result = deliver.send_email("<p>hi</p>", subject="Test Digest")

    assert result is True
    smtp = FakeSMTP.instances[0]
    assert smtp.starttls_called
    assert smtp.login_args == ("sender@example.com", "secret")
    from_addr, to_addrs, msg = smtp.sendmail_args
    # the critical fix: to_addrs must be a list of individual addresses,
    # never a single comma-joined string (which breaks the RCPT TO envelope)
    assert to_addrs == ["a@example.com", "b@example.com"]
    assert "a@example.com, b@example.com" in msg  # header stays human-readable


def test_send_email_single_recipient(monkeypatch):
    _clear_resend(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("DIGEST_EMAIL_TO", "solo@example.com")
    monkeypatch.setenv("DIGEST_EMAIL_FROM", "sender@example.com")
    monkeypatch.setattr(deliver.smtplib, "SMTP", FakeSMTP)

    deliver.send_email("<p>hi</p>", subject="Test")
    _, to_addrs, _ = FakeSMTP.instances[0].sendmail_args
    assert to_addrs == ["solo@example.com"]


def test_send_email_smtp_attaches_files(monkeypatch, tmp_path):
    _clear_resend(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("DIGEST_EMAIL_TO", "solo@example.com")
    monkeypatch.setenv("DIGEST_EMAIL_FROM", "sender@example.com")
    monkeypatch.setattr(deliver.smtplib, "SMTP", FakeSMTP)

    pdf_path = tmp_path / "resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf content")

    deliver.send_email("<p>hi</p>", subject="Test", attachments=[pdf_path])
    _, _, msg = FakeSMTP.instances[0].sendmail_args
    assert "resume.pdf" in msg
    assert "application/octet-stream" in msg or "Content-Disposition" in msg


def test_send_email_noop_when_not_configured(monkeypatch):
    _clear_resend(monkeypatch)
    for var in ("SMTP_HOST", "DIGEST_EMAIL_TO", "DIGEST_EMAIL_FROM", "SMTP_USER"):
        monkeypatch.delenv(var, raising=False)
    result = deliver.send_email("<p>hi</p>", subject="Test")
    assert result is False
    assert FakeSMTP.instances == []


def test_send_email_noop_when_no_recipients(monkeypatch):
    monkeypatch.delenv("DIGEST_EMAIL_TO", raising=False)
    result = deliver.send_email("<p>hi</p>", subject="Test")
    assert result is False


class FakeResendResponse:
    status_code = 200

    def raise_for_status(self):
        pass


def test_send_email_prefers_resend_when_configured(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("RESEND_FROM", "test@resend.dev")
    monkeypatch.setenv("DIGEST_EMAIL_TO", "a@example.com, b@example.com")
    # SMTP is also "configured" here to prove Resend wins when both are set
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(deliver.smtplib, "SMTP", FakeSMTP)

    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json))
        return FakeResendResponse()

    monkeypatch.setattr(deliver.requests, "post", fake_post)

    result = deliver.send_email("<p>hi</p>", subject="Test Digest")

    assert result is True
    assert FakeSMTP.instances == []  # never touched SMTP
    url, headers, payload = calls[0]
    assert url == deliver.RESEND_API_URL
    assert headers["Authorization"] == "Bearer re_test_key"
    assert payload["from"] == "test@resend.dev"
    assert payload["to"] == ["a@example.com", "b@example.com"]
    assert payload["subject"] == "Test Digest"
    assert "attachments" not in payload


def test_send_email_resend_encodes_attachments(monkeypatch, tmp_path):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("DIGEST_EMAIL_TO", "a@example.com")

    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return FakeResendResponse()

    monkeypatch.setattr(deliver.requests, "post", fake_post)

    pdf_content = b"%PDF-1.4 fake pdf content for resend test"
    pdf_path = tmp_path / "tailored_resume.pdf"
    pdf_path.write_bytes(pdf_content)

    deliver.send_email("<p>hi</p>", subject="Test", attachments=[pdf_path])

    payload = calls[0]
    assert len(payload["attachments"]) == 1
    attachment = payload["attachments"][0]
    assert attachment["filename"] == "tailored_resume.pdf"
    assert base64.b64decode(attachment["content"]) == pdf_content
