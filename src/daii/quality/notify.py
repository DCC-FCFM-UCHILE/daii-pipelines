"""Alerta por email (SMTP, stdlib). Sin SMTP_HOST configurado solo se loguea."""

import os
import smtplib
from email.message import EmailMessage

from daii.log import logger


def report(results: list[dict], extra: str = "") -> str:
    lines = [f"[{r['status'].upper()}] {r['spider']} ({r['run_id']}): " + "; ".join(r["problems"]) for r in results]
    return "\n".join(lines + ([extra] if extra else []))


def send(subject: str, body: str) -> bool:
    host = os.environ.get("SMTP_HOST")
    if not host:
        logger.bind(evento="alerta_no_enviada").warning(f"SMTP_HOST no configurado:\n{body}")
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
        logger.bind(evento="alerta_no_enviada").opt(exception=True).error(f"falló el envío por email:\n{body}")
        return False
    logger.bind(evento="alerta_enviada").info(subject)
    return True
