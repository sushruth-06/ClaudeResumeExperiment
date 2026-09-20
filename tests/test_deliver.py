from __future__ import annotations

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


def test_send_email_splits_comma_separated_recipients(monkeypatch):
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
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("DIGEST_EMAIL_TO", "solo@example.com")
    monkeypatch.setenv("DIGEST_EMAIL_FROM", "sender@example.com")
    monkeypatch.setattr(deliver.smtplib, "SMTP", FakeSMTP)

    deliver.send_email("<p>hi</p>", subject="Test")
    _, to_addrs, _ = FakeSMTP.instances[0].sendmail_args
    assert to_addrs == ["solo@example.com"]


def test_send_email_noop_when_not_configured(monkeypatch):
    for var in ("SMTP_HOST", "DIGEST_EMAIL_TO", "DIGEST_EMAIL_FROM", "SMTP_USER"):
        monkeypatch.delenv(var, raising=False)
    result = deliver.send_email("<p>hi</p>", subject="Test")
    assert result is False
    assert FakeSMTP.instances == []
