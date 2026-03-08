#!/usr/bin/env python3
"""Email delivery services."""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Iterable

import requests

logger = logging.getLogger(__name__)

MAILGUN_US_BASE_URL = "https://api.mailgun.net"
MAILGUN_EU_BASE_URL = "https://api.eu.mailgun.net"
DEFAULT_TIMEOUT_SECONDS = 15


def _strip(value: str | None) -> str:
    return (value or "").strip()


def _coerce_recipients(to: str | Iterable[str] | None) -> list[str]:
    if to is None:
        return []
    if isinstance(to, str):
        return [item.strip() for item in to.split(",") if item.strip()]
    return [str(item).strip() for item in to if str(item).strip()]


@dataclass
class EmailResult:
    """Result of an email send or validation attempt."""

    success: bool
    message_id: str | None = None
    error: str | None = None
    provider: str | None = None


class DisabledEmailService:
    """No-op service used when no provider is configured."""

    def __init__(self, reason: str = "Email delivery is not configured"):
        self.reason = reason

    @property
    def provider_name(self) -> str:
        return "disabled"

    @property
    def is_configured(self) -> bool:
        return False

    @property
    def default_from(self) -> str:
        return ""

    def validate(self) -> EmailResult:
        return EmailResult(success=False, error=self.reason, provider=self.provider_name)

    def send(self, to=None, subject=None, text=None, html=None, **kwargs) -> EmailResult:
        logger.warning("EMAIL BLOCKED: attempted send to %r subject=%r. %s", to, subject, self.reason)
        return EmailResult(success=False, error=self.reason, provider=self.provider_name)

    def send_alert(self, to=None, title=None, items=None, **kwargs) -> EmailResult:
        logger.warning("EMAIL BLOCKED: attempted alert to %r title=%r. %s", to, title, self.reason)
        return EmailResult(success=False, error=self.reason, provider=self.provider_name)


class MailgunEmailService:
    """Mailgun HTTP API email service."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        domain: str | None = None,
        from_email: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.api_key = _strip(api_key or os.getenv("MAILGUN_API_KEY"))
        self.domain = _strip(domain or os.getenv("MAILGUN_DOMAIN"))
        self._from_email = _strip(from_email or os.getenv("MAILGUN_FROM_EMAIL"))
        self.timeout_seconds = timeout_seconds

        configured_base = _strip(base_url or os.getenv("MAILGUN_BASE_URL"))
        region = _strip(os.getenv("MAILGUN_REGION")).lower()
        if configured_base:
            self.base_url = configured_base.rstrip("/")
        elif region == "eu":
            self.base_url = MAILGUN_EU_BASE_URL
        else:
            self.base_url = MAILGUN_US_BASE_URL

    @property
    def provider_name(self) -> str:
        return "mailgun"

    @property
    def default_from(self) -> str:
        return self._from_email

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.domain and self._from_email)

    def validate(self) -> EmailResult:
        if not self.is_configured:
            return EmailResult(
                success=False,
                error="MAILGUN_API_KEY, MAILGUN_DOMAIN, or MAILGUN_FROM_EMAIL not configured",
                provider=self.provider_name,
            )

        try:
            response = requests.get(
                f"{self.base_url}/v3/domains/{self.domain}",
                auth=("api", self.api_key),
                timeout=self.timeout_seconds,
            )
            if response.ok:
                return EmailResult(success=True, message_id=self.domain, provider=self.provider_name)
            return EmailResult(
                success=False,
                error=f"HTTP {response.status_code}: {response.text[:200]}",
                provider=self.provider_name,
            )
        except Exception as exc:
            return EmailResult(success=False, error=str(exc), provider=self.provider_name)

    def send(
        self,
        to=None,
        subject=None,
        text=None,
        html=None,
        *,
        tags: list[str] | None = None,
        reply_to: str | None = None,
        test_mode: bool = False,
        **kwargs,
    ) -> EmailResult:
        recipients = _coerce_recipients(to)
        if not self.is_configured:
            return EmailResult(
                success=False,
                error="MAILGUN_API_KEY, MAILGUN_DOMAIN, or MAILGUN_FROM_EMAIL not configured",
                provider=self.provider_name,
            )
        if not recipients:
            return EmailResult(success=False, error="No recipients provided", provider=self.provider_name)
        if not text and not html:
            return EmailResult(success=False, error="Email body is empty", provider=self.provider_name)

        payload: list[tuple[str, str]] = [("from", self.default_from)]
        payload.extend(("to", recipient) for recipient in recipients)
        payload.append(("subject", subject or "(no subject)"))
        if text:
            payload.append(("text", text))
        if html:
            payload.append(("html", html))
        if reply_to:
            payload.append(("h:Reply-To", reply_to))
        if test_mode:
            payload.append(("o:testmode", "yes"))
        for tag in tags or []:
            cleaned = _strip(tag)
            if cleaned:
                payload.append(("o:tag", cleaned))

        try:
            response = requests.post(
                f"{self.base_url}/v3/{self.domain}/messages",
                auth=("api", self.api_key),
                data=payload,
                timeout=self.timeout_seconds,
            )
            if response.ok:
                data = response.json()
                return EmailResult(
                    success=True,
                    message_id=data.get("id"),
                    provider=self.provider_name,
                )
            return EmailResult(
                success=False,
                error=f"HTTP {response.status_code}: {response.text[:200]}",
                provider=self.provider_name,
            )
        except Exception as exc:
            logger.error("Mailgun send failed: %s", exc)
            return EmailResult(success=False, error=str(exc), provider=self.provider_name)

    def send_alert(self, to=None, title=None, items=None, **kwargs) -> EmailResult:
        recipients = _coerce_recipients(to) or _coerce_recipients(os.getenv("ALERT_EMAIL_TO"))
        body_lines: list[str] = []
        if isinstance(items, str):
            body_lines = [items]
        elif isinstance(items, Iterable):
            body_lines = [str(item) for item in items]
        text = "\n".join(line for line in body_lines if line)
        return self.send(
            to=recipients,
            subject=title or "Engineering alert",
            text=text or (title or "Engineering alert"),
            tags=["alert"],
            **kwargs,
        )


class GmailEmailService:
    """Gmail SMTP email service."""

    def __init__(
        self,
        *,
        email_address: str | None = None,
        app_password: str | None = None,
        from_email: str | None = None,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.email_address = _strip(email_address or os.getenv("GMAIL_EMAIL"))
        self.app_password = _strip(app_password or os.getenv("GMAIL_APP_PASSWORD"))
        self._from_email = _strip(from_email or os.getenv("GMAIL_FROM_EMAIL") or self.email_address)
        self.smtp_host = _strip(smtp_host or os.getenv("GMAIL_SMTP_HOST") or "smtp.gmail.com")
        self.smtp_port = smtp_port or int(os.getenv("GMAIL_SMTP_PORT", "465"))
        self.timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "gmail"

    @property
    def default_from(self) -> str:
        return self._from_email

    @property
    def is_configured(self) -> bool:
        return bool(self.email_address and self.app_password and self._from_email)

    def validate(self) -> EmailResult:
        if not self.is_configured:
            return EmailResult(
                success=False,
                error="GMAIL_EMAIL or GMAIL_APP_PASSWORD not configured",
                provider=self.provider_name,
            )

        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=self.timeout_seconds) as smtp:
                smtp.login(self.email_address, self.app_password)
            return EmailResult(success=True, message_id=self.email_address, provider=self.provider_name)
        except Exception as exc:
            return EmailResult(success=False, error=str(exc), provider=self.provider_name)

    def send(self, to=None, subject=None, text=None, html=None, **kwargs) -> EmailResult:
        recipients = _coerce_recipients(to)
        if not self.is_configured:
            return EmailResult(
                success=False,
                error="GMAIL_EMAIL or GMAIL_APP_PASSWORD not configured",
                provider=self.provider_name,
            )
        if not recipients:
            return EmailResult(success=False, error="No recipients provided", provider=self.provider_name)
        if not text and not html:
            return EmailResult(success=False, error="Email body is empty", provider=self.provider_name)

        message = EmailMessage()
        message["From"] = self.default_from
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject or "(no subject)"
        if text:
            message.set_content(text)
        else:
            message.set_content("This message contains HTML content.")
        if html:
            message.add_alternative(html, subtype="html")

        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=self.timeout_seconds) as smtp:
                smtp.login(self.email_address, self.app_password)
                smtp.send_message(message)
            return EmailResult(success=True, message_id=message["Message-ID"], provider=self.provider_name)
        except Exception as exc:
            logger.error("Gmail send failed: %s", exc)
            return EmailResult(success=False, error=str(exc), provider=self.provider_name)

    def send_alert(self, to=None, title=None, items=None, **kwargs) -> EmailResult:
        recipients = _coerce_recipients(to) or _coerce_recipients(os.getenv("ALERT_EMAIL_TO"))
        body_lines: list[str] = []
        if isinstance(items, str):
            body_lines = [items]
        elif isinstance(items, Iterable):
            body_lines = [str(item) for item in items]
        text = "\n".join(line for line in body_lines if line)
        return self.send(
            to=recipients,
            subject=title or "Engineering alert",
            text=text or (title or "Engineering alert"),
            **kwargs,
        )


class EmailService:
    """Provider facade used across the app."""

    def __init__(self, provider: str | None = None):
        selected = _strip(provider or os.getenv("EMAIL_PROVIDER")).lower()
        if selected in ("", "auto"):
            if MailgunEmailService().is_configured:
                selected = "mailgun"
            elif GmailEmailService().is_configured:
                selected = "gmail"
            else:
                selected = "disabled"

        if selected == "mailgun":
            self._impl = MailgunEmailService()
        elif selected in ("gmail", "smtp"):
            self._impl = GmailEmailService()
        else:
            self._impl = DisabledEmailService()

    @property
    def provider_name(self) -> str:
        return self._impl.provider_name

    @property
    def is_configured(self) -> bool:
        return self._impl.is_configured

    @property
    def default_from(self) -> str:
        return self._impl.default_from

    def validate(self) -> EmailResult:
        return self._impl.validate()

    def send(self, *args, **kwargs) -> EmailResult:
        return self._impl.send(*args, **kwargs)

    def send_alert(self, *args, **kwargs) -> EmailResult:
        return self._impl.send_alert(*args, **kwargs)


def get_email_service(provider: str | None = None) -> EmailService:
    """Return the configured email service facade."""
    return EmailService(provider=provider)


def send_email(to=None, subject=None, text=None, html=None) -> EmailResult:
    """Send a general email with the configured provider."""
    return get_email_service().send(to=to, subject=subject, text=text, html=html)


def send_email_gmail(to=None, subject=None, text=None, html=None) -> EmailResult:
    """Send an email explicitly through Gmail SMTP."""
    return GmailEmailService().send(to=to, subject=subject, text=text, html=html)
