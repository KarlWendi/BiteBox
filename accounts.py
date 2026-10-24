"""Persistent accounts, password hashes and revocable login sessions."""
import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from database import connect
from notifications import send_verification_email

SESSION_SECONDS = 3600
PASSWORD_ROUNDS = 600_000


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), PASSWORD_ROUNDS).hex()
    return f'{salt}:{digest}'


def password_matches(password, stored):
    salt, expected = stored.split(':')
    actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), PASSWORD_ROUNDS).hex()
    return secrets.compare_digest(actual, expected)


def normalise_username(username):
    username = username.strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,39}', username):
        raise HTTPException(422, 'Use 3–40 letters, numbers, dots, hyphens or underscores for your username.')
    return username


def normalise_email(email):
    if not email:
        return None
    email = email.strip().lower()
    if not re.fullmatch(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
        raise HTTPException(422, 'Please enter a valid email address.')
    return email


def initialise_accounts(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('customer', 'staff', 'admin')),
        active INTEGER NOT NULL DEFAULT 1)""")

    user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
    if "email" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN email TEXT")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email) WHERE email IS NOT NULL")
    if "email_verified" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")

    connection.execute("""CREATE TABLE IF NOT EXISTS email_verifications (
        id INTEGER PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        user_id INTEGER NOT NULL REFERENCES users(id),
        expires_at REAL NOT NULL,
        used_at REAL)""")

    connection.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        expires_at REAL NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS login_attempts (
        bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at REAL NOT NULL)""")
    username = os.environ.get('TAKEAWAY_ADMIN_USERNAME', '')
    connection.execute("""CREATE TABLE IF NOT EXISTS admin_invitations (
        id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
        created_by INTEGER NOT NULL REFERENCES users(id), expires_at REAL NOT NULL,
        used_at REAL, revoked INTEGER NOT NULL DEFAULT 0)""")
    password = os.environ.get('TAKEAWAY_ADMIN_PASSWORD', '')
    if not username and not password:
        return
    username = normalise_username(username)
    if not 16 <= len(password) <= 128:
        raise ValueError('TAKEAWAY_ADMIN_PASSWORD must contain 16–128 characters.')
    existing = connection.execute('SELECT role FROM users WHERE username = ?', (username,)).fetchone()
    if existing:
        if existing['role'] != 'admin':
            raise ValueError('The configured admin username belongs to a non-admin account. Choose a different admin username.')
        return
    # Bootstrap only once. Subsequent restarts must not create additional admins.
    if connection.execute("SELECT 1 FROM users WHERE role = 'admin'").fetchone():
        return
    connection.execute('INSERT INTO users (username, password_hash, role, email_verified) VALUES (?, ?, ?, 1)',
                       (username, password_hash(password), 'admin'))


def public_user(row):
    user_dict = {key: row[key] for key in ('id', 'username', 'role', 'active') if key in row.keys()}
    if 'email' in row.keys():
        user_dict['email'] = row['email']
    if 'email_verified' in row.keys():
        user_dict['email_verified'] = bool(row['email_verified'])
    return user_dict


def session_user(request, required=True):
    authorization = request.headers.get('Authorization', '')
    if not authorization:
        if required:
            raise HTTPException(401, 'Please sign in.')
        return None
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 128:
        raise HTTPException(401, 'Please sign in again.')
    digest = hashlib.sha256(token.encode()).hexdigest()
    with closing(connect(request.app.state.database_path)) as connection:
        user = connection.execute("""SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE token_hash = ? AND expires_at > ? AND active = 1""", (digest, time.time())).fetchone()
    if user is None:
        raise HTTPException(401, 'Your session has expired. Please sign in again.')
    return public_user(user)


def require_account(request: Request):
    return session_user(request)


def optional_account(request: Request):
    # Existing HTTP Basic clients may still place guest orders.
    if request.headers.get('Authorization', '').lower().startswith('basic '):
        return None
    return session_user(request, required=False)


def require_admin(request: Request):
    user = session_user(request)
    if user['role'] != 'admin':
        raise HTTPException(403, 'Administrator access required.')
    return user


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=12, max_length=128)
    email: Optional[str] = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=128)


class VerifyEmailRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=20, max_length=128)


class ResendVerificationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: Optional[str] = Field(default=None, max_length=120)


class InvitationRegistration(Credentials):
    token: str = Field(min_length=20, max_length=128)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class AccountState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active: bool = Field(strict=True)


class StockUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stock: int = Field(strict=True, ge=0, le=10000)


def throttle(connection, buckets):
    """Persist limits so restarting a worker does not bypass them."""
    now = time.time()
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('DELETE FROM login_attempts WHERE expires_at <= ?', (now,))
        for bucket, limit in buckets:
            row = connection.execute('SELECT count FROM login_attempts WHERE bucket = ?', (bucket,)).fetchone()
            if row and row['count'] >= limit:
                raise HTTPException(429, 'Too many attempts. Please try again in 15 minutes.')
        for bucket, _ in buckets:
            connection.execute("""INSERT INTO login_attempts VALUES (?, 1, ?)
                ON CONFLICT(bucket) DO UPDATE SET count = count + 1""", (bucket, now + 900))


def account_router():
    router = APIRouter()

    @router.post('/admin/invitations', status_code=201)
    def invite_admin(request: Request, user=Depends(require_admin)):
        token = secrets.token_urlsafe(32)
        expires = time.time() + 86400
        with closing(connect(request.app.state.database_path)) as connection:
            throttle(connection, [('invite:' + str(user['id']), 20)])
            with connection:
                cursor = connection.execute(
                    'INSERT INTO admin_invitations (token_hash, created_by, expires_at) VALUES (?, ?, ?)',
                    (hashlib.sha256(token.encode()).hexdigest(), user['id'], expires))
        return {'id': cursor.lastrowid, 'token': token, 'expires_at': expires}

    @router.get('/admin/invitations', dependencies=[Depends(require_admin)])
    def invitations(request: Request):
        with closing(connect(request.app.state.database_path)) as connection:
            rows = connection.execute('SELECT id, created_by, expires_at, used_at, revoked FROM admin_invitations ORDER BY id DESC').fetchall()
        return [dict(row) for row in rows]

    @router.delete('/admin/invitations/{invitation_id}', dependencies=[Depends(require_admin)])
    def revoke_invitation(invitation_id: int, request: Request):
        with closing(connect(request.app.state.database_path)) as connection, connection:
            result = connection.execute('UPDATE admin_invitations SET revoked = 1 WHERE id = ?', (invitation_id,))
            if not result.rowcount:
                raise HTTPException(404, 'Invitation not found.')
        return {'revoked': True}

    @router.post('/auth/accept-invitation', status_code=201)
    def accept_invitation(body: InvitationRegistration, request: Request):
        username = normalise_username(body.username)
        email = normalise_email(body.email)
        digest = hashlib.sha256(body.token.encode()).hexdigest()
        with closing(connect(request.app.state.database_path)) as connection:
            address = request.client.host if request.client else 'unknown'
            throttle(connection, [('accept-invite:' + address, 30)])
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                invitation = connection.execute("""SELECT i.id FROM admin_invitations i
                    JOIN users u ON u.id = i.created_by
                    WHERE i.token_hash = ? AND i.expires_at > ? AND i.used_at IS NULL
                    AND i.revoked = 0 AND u.active = 1 AND u.role = 'admin'""", (digest, time.time())).fetchone()
                if not invitation:
                    raise HTTPException(400, 'This invitation is invalid, expired, revoked or already used. Ask an administrator for a new link.')
                try:
                    cursor = connection.execute('INSERT INTO users (username, password_hash, role, email, email_verified) VALUES (?, ?, ?, ?, 1)',
                                                (username, password_hash(body.password), 'admin', email))
                except sqlite3.IntegrityError as error:
                    error_msg = str(error).lower()
                    if 'email' in error_msg:
                        raise HTTPException(409, 'That email address is already registered.') from error
                    raise HTTPException(409, 'That username is unavailable. Choose another username; your invitation is still valid.') from error
                connection.execute('UPDATE admin_invitations SET used_at = ? WHERE id = ?', (time.time(), invitation['id']))
                return {'id': cursor.lastrowid, 'username': username, 'role': 'admin', 'active': 1, 'email': email, 'email_verified': True}

    def create_user(connection, credentials, role):
        username = normalise_username(credentials.username)
        email = normalise_email(credentials.email)
        email_verified = 0 if email else 1
        try:
            with connection:
                cursor = connection.execute('INSERT INTO users (username, password_hash, role, email, email_verified) VALUES (?, ?, ?, ?, ?)',
                                            (username, password_hash(credentials.password), role, email, email_verified))
                user_id = cursor.lastrowid
                token = None
                if email:
                    token = secrets.token_urlsafe(32)
                    expires = time.time() + 86400
                    connection.execute('INSERT INTO email_verifications (token_hash, user_id, expires_at) VALUES (?, ?, ?)',
                                       (hashlib.sha256(token.encode()).hexdigest(), user_id, expires))
                    send_verification_email(email, username, token)
                res = {'id': user_id, 'username': username, 'role': role, 'active': 1, 'email': email, 'email_verified': bool(email_verified)}
                if token:
                    res['verification_token'] = token
                return res
        except sqlite3.IntegrityError as error:
            error_msg = str(error).lower()
            if 'email' in error_msg:
                raise HTTPException(409, 'That email address is already registered.') from error
            raise HTTPException(409, 'That username is unavailable.') from error

    @router.post('/auth/register', status_code=201)
    def register(credentials: Credentials, request: Request):
        with closing(connect(request.app.state.database_path)) as connection:
            address = request.client.host if request.client else 'unknown'
            throttle(connection, [('register:' + address, 30)])
            return create_user(connection, credentials, 'customer')

    @router.post('/auth/verify-email')
    def verify_email(body: VerifyEmailRequest, request: Request):
        digest = hashlib.sha256(body.token.encode()).hexdigest()
        with closing(connect(request.app.state.database_path)) as connection, connection:
            row = connection.execute("""SELECT v.id, v.user_id FROM email_verifications v
                WHERE v.token_hash = ? AND v.expires_at > ? AND v.used_at IS NULL""",
                (digest, time.time())).fetchone()
            if not row:
                raise HTTPException(400, 'Invalid or expired email verification token.')
            connection.execute('UPDATE users SET email_verified = 1 WHERE id = ?', (row['user_id'],))
            connection.execute('UPDATE email_verifications SET used_at = ? WHERE id = ?', (time.time(), row['id']))
        return {'verified': True}

    @router.post('/auth/resend-verification')
    def resend_verification(body: ResendVerificationRequest, request: Request):
        email = normalise_email(body.email) if body.email else None
        if not email:
            raise HTTPException(422, 'Please provide an email address.')
        with closing(connect(request.app.state.database_path)) as connection:
            user = connection.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            if not user:
                return {'sent': True}
            if user['email_verified']:
                return {'sent': True, 'already_verified': True}
            token = secrets.token_urlsafe(32)
            expires = time.time() + 86400
            with connection:
                connection.execute('INSERT INTO email_verifications (token_hash, user_id, expires_at) VALUES (?, ?, ?)',
                                   (hashlib.sha256(token.encode()).hexdigest(), user['id'], expires))
            send_verification_email(user['email'], user['username'], token)
            return {'sent': True, 'token': token}

    @router.post('/auth/login')
    def login(credentials: LoginRequest, request: Request):
        identifier = credentials.username.strip()
        is_email = '@' in identifier
        if is_email:
            try:
                identifier = normalise_email(identifier)
            except HTTPException:
                identifier = identifier.lower()
        else:
            try:
                identifier = normalise_username(identifier)
            except HTTPException:
                identifier = identifier.lower()

        with closing(connect(request.app.state.database_path)) as connection:
            address = request.client.host if request.client else 'unknown'
            throttle(connection, [('user:' + identifier, 10), ('login:' + address, 100)])
            if is_email:
                user = connection.execute('SELECT * FROM users WHERE email = ?', (identifier,)).fetchone()
            else:
                user = connection.execute('SELECT * FROM users WHERE username = ?', (identifier,)).fetchone()
                if not user:
                    user = connection.execute('SELECT * FROM users WHERE email = ?', (identifier,)).fetchone()

            valid = password_matches(credentials.password, user['password_hash'] if user else '0' * 32 + ':' + '0' * 64)
            if not valid or not user or not user['active']:
                raise HTTPException(401, 'Incorrect username or password.')

            if user['email'] and not user['email_verified']:
                raise HTTPException(403, 'Email address not verified. Please check your email for the verification link.')

            token = secrets.token_urlsafe(32)
            expires = time.time() + SESSION_SECONDS
            with connection:
                connection.execute('DELETE FROM sessions WHERE expires_at <= ?', (time.time(),))
                connection.execute('DELETE FROM login_attempts WHERE bucket = ?', ('user:' + identifier,))
                connection.execute('INSERT INTO sessions VALUES (?, ?, ?)',
                                   (hashlib.sha256(token.encode()).hexdigest(), user['id'], expires))
            return {'token': token, 'expires_at': expires, 'user': public_user(user)}

    @router.get('/auth/me')
    def me(user=Depends(require_account)):
        return user

    @router.post('/auth/logout')
    def logout(request: Request):
        authorization = request.headers.get('Authorization', '')
        token = authorization.partition(' ')[2]
        with closing(connect(request.app.state.database_path)) as connection, connection:
            connection.execute('DELETE FROM sessions WHERE token_hash = ?', (hashlib.sha256(token.encode()).hexdigest(),))
        return {'signed_out': True}

    @router.post('/auth/password')
    def change_password(body: PasswordChange, request: Request, user=Depends(require_account)):
        with closing(connect(request.app.state.database_path)) as connection:
            throttle(connection, [('password:' + str(user['id']), 10)])
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                stored = connection.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()[0]
                if not password_matches(body.current_password, stored):
                    raise HTTPException(401, 'Current password is incorrect.')
                connection.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash(body.new_password), user['id']))
                connection.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
        return {'signed_out': True}

    @router.get('/admin/users', dependencies=[Depends(require_admin)])
    def users(request: Request):
        with closing(connect(request.app.state.database_path)) as connection:
            return [public_user(row) for row in connection.execute('SELECT * FROM users ORDER BY id')]

    @router.post('/admin/staff', status_code=201, dependencies=[Depends(require_admin)])
    def create_staff(credentials: Credentials, request: Request):
        with closing(connect(request.app.state.database_path)) as connection:
            return create_user(connection, credentials, 'staff')

    @router.patch('/admin/users/{user_id}', dependencies=[Depends(require_admin)])
    def set_active(user_id: int, body: AccountState, request: Request):
        with closing(connect(request.app.state.database_path)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            user = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
            if not user:
                raise HTTPException(404, 'Account not found.')
            if user['role'] == 'admin':
                raise HTTPException(409, 'The administrator account cannot be disabled here.')
            connection.execute('UPDATE users SET active = ? WHERE id = ?', (int(body.active), user_id))
            connection.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
        return {'id': user_id, 'active': body.active}

    @router.patch('/admin/menu/{item_id}', dependencies=[Depends(require_admin)])
    def set_stock(item_id: int, body: StockUpdate, request: Request):
        with closing(connect(request.app.state.database_path)) as connection, connection:
            result = connection.execute('UPDATE products SET stock = ? WHERE id = ?', (body.stock, item_id))
            if not result.rowcount:
                raise HTTPException(404, 'Menu item not found.')
        return {'id': item_id, 'stock': body.stock}

    return router
