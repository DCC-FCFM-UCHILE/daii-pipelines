"""Alerta por email (SMTP, stdlib). Sin SMTP_HOST configurado solo se loguea."""

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)


def report(results: list[dict], extra: str = "") -> str:
    lines = [f"[{r['status'].upper()}] {r['spider']} ({r['run_id']}): " + "; ".join(r["problems"]) for r in results]
    return "\n".join(lines + ([extra] if extra else []))


def send(subject: str, body: str) -> bool:
    host = os.environ.get("SMTP_HOST")
    if not host:
        log.warning("SMTP_HOST no configurado; alerta no enviada:\n%s", body)
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ.get("ALERT_FROM", ""), os.environ.get("ALERT_TO", "")
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as s:
            s.starttls()
            if user := os.environ.get("SMTP_USER"):
                s.login(user, os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    except Exception:  # un SMTP caído no debe tapar el error original ni fallar un pipeline sano
        log.exception("no se pudo enviar la alerta por email:\n%s", body)
        return False
    return True
