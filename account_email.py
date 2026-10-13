"""Email verification and recovery; only token hashes are persisted."""
import hashlib
import os
import re
import secrets
import smtplib
import ssl
import time
from contextlib import closing
from email.message import EmailMessage
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from database import connect


def email_enabled():
    return os.environ.get('TAKEAWAY_EMAIL_ENABLED') == '1'


def normalise_email(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", value):
        raise HTTPException(422, 'Enter a valid email address.')
    return value


def mail_ready():
    if not all(os.environ.get(key) for key in ('SMTP_HOST', 'SMTP_FROM', 'TAKEAWAY_WEBSITE_URL')):
        raise HTTPException(503, 'Account emails are not configured yet. Please contact the site administrator.')
    url = urlsplit(os.environ['TAKEAWAY_WEBSITE_URL'])
    if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1')):
        raise HTTPException(503, 'Account email links need a secure website address.')


def send_email(address, kind, token):
    mail_ready()
    base = os.environ['TAKEAWAY_WEBSITE_URL'].rstrip('/') + '/'
    link = base + '?' + urlencode({kind + '_account': token})
    message = EmailMessage()
    message['From'] = os.environ['SMTP_FROM']
    message['To'] = address
    message['Subject'] = 'Verify your BiteBox email' if kind == 'verify' else 'Reset your BiteBox password'
    lifetime = '24 hours' if kind == 'verify' else '30 minutes'
    message.set_content(f"{message['Subject']}\n\nOpen this link: {link}\n\nIt expires in {lifetime} and works once. If you did not request this email, ignore it.")
    try:
        port = int(os.environ.get('SMTP_PORT', '465'))
        if port == 465:
            smtp = smtplib.SMTP_SSL(os.environ['SMTP_HOST'], port, timeout=15, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(os.environ['SMTP_HOST'], port, timeout=15)
        with smtp:
            if port != 465:
                smtp.starttls(context=ssl.create_default_context())
            if os.environ.get('SMTP_USERNAME'):
                smtp.login(os.environ['SMTP_USERNAME'], os.environ.get('SMTP_PASSWORD', ''))
            smtp.send_message(message)
    except (OSError, ValueError, smtplib.SMTPException) as error:
        raise HTTPException(503, 'Email delivery failed. Please try requesting a new link shortly.') from error


def issue_link(connection, user_id, address, kind):
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connection:
        connection.execute('DELETE FROM account_links WHERE expires_at <= ?', (time.time(),))
        connection.execute('INSERT INTO account_links VALUES (?, ?, ?, ?, ?)',
                           (digest, user_id, address, kind, time.time() + (86400 if kind == 'verify' else 1800)))
    try:
        send_email(address, kind, token)
    except HTTPException:
        with connection:
            connection.execute('DELETE FROM account_links WHERE token_hash = ?', (digest,))
        raise


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)


class EmailAttachment(EmailRequest):
    password: str = Field(min_length=1, max_length=128)


class LinkToken(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=20, max_length=128)


class ResetPassword(LinkToken):
    password: str = Field(min_length=12, max_length=128)


def email_router():
    from accounts import require_account, password_matches, password_hash, throttle
    from fastapi import Depends
    router = APIRouter()

    @router.get('/auth/options')
    def options():
        return {'email_enabled': email_enabled()}

    @router.post('/auth/email')
    def attach_email(body: EmailAttachment, request: Request, user=Depends(require_account)):
        """Give legacy accounts a recovery address after password confirmation."""
        mail_ready()
        email = normalise_email(body.email)
        with closing(connect(request.app.state.database_path)) as db:
            throttle(db, [('attach-email:' + str(user['id']), 5)])
            with db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM users WHERE id = ?', (user['id'],)).fetchone()
                if not password_matches(body.password, row['password_hash']):
                    raise HTTPException(401, 'Current password is incorrect.')
                if row['email_verified'] and row['email']:
                    raise HTTPException(409, 'This account already has a verified email address.')
                if db.execute('SELECT 1 FROM users WHERE email = ? AND id != ?', (email, user['id'])).fetchone():
                    raise HTTPException(409, 'That email address is unavailable.')
                db.execute('UPDATE users SET email = ?, email_verified = 0 WHERE id = ?', (email, user['id']))
                db.execute('DELETE FROM account_links WHERE user_id = ?', (user['id'],))
            issue_link(db, user['id'], email, 'verify')
        return {'message': 'Check your email to verify your recovery address.'}

    def request_link(body, request, kind):
        mail_ready()
        email = normalise_email(body.email)
        with closing(connect(request.app.state.database_path)) as db:
            address = request.client.host if request.client else 'unknown'
            throttle(db, [('email-ip:' + address, 30), ('email:' + email, 5)])
            row = db.execute('SELECT * FROM users WHERE email = ? AND active = 1', (email,)).fetchone()
            if row and ((kind == 'verify' and not row['email_verified']) or (kind == 'reset' and row['email_verified'])):
                issue_link(db, row['id'], email, kind)
        return {'message': 'If an eligible account exists, an email has been sent. Check your inbox and spam folder.'}

    @router.post('/auth/resend-verification')
    def resend(body: EmailRequest, request: Request):
        return request_link(body, request, 'verify')

    @router.post('/auth/forgot-password')
    def forgot(body: EmailRequest, request: Request):
        return request_link(body, request, 'reset')

    def consume(body, request, kind):
        hashed = password_hash(body.password) if kind == 'reset' else None
        with closing(connect(request.app.state.database_path)) as db:
            address = request.client.host if request.client else 'unknown'
            throttle(db, [('consume-link:' + address, 30)])
            with db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('''SELECT l.user_id FROM account_links l JOIN users u ON u.id = l.user_id
                    WHERE l.token_hash = ? AND l.kind = ? AND l.expires_at > ?
                    AND u.active = 1 AND u.email = l.email''',
                    (hashlib.sha256(body.token.encode()).hexdigest(), kind, time.time())).fetchone()
                if not row:
                    raise HTTPException(400, 'This link is invalid, expired or already used. Request a new email.')
                if kind == 'verify':
                    db.execute('UPDATE users SET email_verified = 1 WHERE id = ?', (row['user_id'],))
                else:
                    db.execute('UPDATE users SET password_hash = ? WHERE id = ?', (hashed, row['user_id']))
                    db.execute('DELETE FROM sessions WHERE user_id = ?', (row['user_id'],))
                db.execute('DELETE FROM account_links WHERE user_id = ? AND kind = ?', (row['user_id'], kind))
        return {'message': 'Email verified. You can now sign in.' if kind == 'verify' else 'Password reset. Sign in with your new password.'}

    @router.post('/auth/verify-email')
    def verify(body: LinkToken, request: Request):
        return consume(body, request, 'verify')

    @router.post('/auth/reset-password')
    def reset(body: ResetPassword, request: Request):
        return consume(body, request, 'reset')

    return router
