import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_customer_email(user, subject, message, html_message=None):
    """Best-effort transactional email. Email outages must not undo a paid order."""
    recipient = (getattr(user, "email", "") or "").strip()
    if not recipient:
        logger.warning("Skipped AKLYTE email: user %s has no email address.", getattr(user, "pk", "?"))
        return False
    try:
        sent = send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
            html_message=html_message,
        )
        return bool(sent)
    except Exception:
        logger.exception("AKLYTE email delivery failed for user %s", getattr(user, "pk", "?"))
        return False


def send_admin_alert(subject, message):
    recipients = getattr(settings, "AKLYTE_ADMIN_EMAILS", [])
    if not recipients:
        logger.info("Admin notification not sent: AKLYTE_ADMIN_EMAILS is empty.")
        return False
    try:
        return bool(send_mail(
            subject=subject, message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients, fail_silently=False,
        ))
    except Exception:
        logger.exception("AKLYTE admin email delivery failed")
        return False
