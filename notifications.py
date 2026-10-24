"""Email notification service for BiteBox."""
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("bitebox.notifications")

# In-memory store for sent emails during testing / runtime
SENT_EMAILS: List[Dict[str, str]] = []


def clear_sent_emails():
    SENT_EMAILS.clear()


def get_sent_emails() -> List[Dict[str, str]]:
    return list(SENT_EMAILS)


def send_email(to_email: str, subject: str, body: str) -> Dict[str, str]:
    email_record = {
        "to": to_email,
        "subject": subject,
        "body": body,
    }
    SENT_EMAILS.append(email_record)
    logger.info(f"EMAIL SENT TO {to_email} | Subject: {subject}\n{body}\n")
    print(f"\n--- EMAIL TO {to_email} ---")
    print(f"Subject: {subject}")
    print(body)
    print("---------------------------\n")
    return email_record


def send_verification_email(to_email: str, username: str, token: str):
    subject = "Verify your BiteBox account email"
    body = (
        f"Hello {username},\n\n"
        f"Thank you for registering with BiteBox! Please use the link or code below to verify your email address:\n\n"
        f"Verification Token: {token}\n\n"
        f"If you did not create a BiteBox account, you can ignore this message."
    )
    return send_email(to_email, subject, body)


def send_order_ready_email(to_email: str, order_id: int, items_summary: str):
    subject = f"Your BiteBox Order #{order_id} is Ready!"
    body = (
        f"Great news!\n\n"
        f"Your BiteBox Order #{order_id} ({items_summary}) is ready for collection.\n\n"
        f"Please show your order number or tracking code at the counter to collect your fresh meal.\n\n"
        f"Thank you for ordering with BiteBox!"
    )
    return send_email(to_email, subject, body)
