"""Persistent accounts, password hashes and revocable login sessions."""
import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from database import connect

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


def validate_password(password):
    if not (8 <= len(password) <= 128):
        raise HTTPException(422, 'Password must be between 8 and 128 characters.')
    if not re.search(r'[A-Z]', password):
        raise HTTPException(422, 'Password must contain at least one uppercase letter.')
    if not re.search(r'[a-z]', password):
        raise HTTPException(422, 'Password must contain at least one lowercase letter.')
    if not re.search(r'[0-9]', password):
        raise HTTPException(422, 'Password must contain at least one digit.')
    if not re.search(r'[^a-zA-Z0-9]', password):
        raise HTTPException(422, 'Password must contain at least one special character.')


def normalise_email(email):
    email = email.strip().lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise HTTPException(422, 'Please enter a valid email address.')
    return email


def normalise_phone(phone):
    phone = phone.strip()
    if not re.fullmatch(r'\+?[0-9\s\-\(\)]{7,20}', phone):
        raise HTTPException(422, 'Please enter a valid phone number.')
    return phone


def normalise_username(username):
    username = username.strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,39}', username):
        raise HTTPException(422, 'Use 3–40 letters, numbers, dots, hyphens or underscores for your username.')
    return username


def initialise_accounts(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        surname TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL UNIQUE DEFAULT '',
        phone_number TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL CHECK(role IN ('customer', 'staff', 'admin')),
        active INTEGER NOT NULL DEFAULT 1,
        email_verified INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL DEFAULT 0)""")

    columns = [row['name'] for row in connection.execute("PRAGMA table_info(users)").fetchall()]
    if columns:
        if 'name' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        if 'surname' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN surname TEXT NOT NULL DEFAULT ''")
        if 'email' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
        if 'phone_number' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN phone_number TEXT NOT NULL DEFAULT ''")
        if 'email_verified' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
        if 'created_at' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN created_at REAL NOT NULL DEFAULT 0")

    connection.execute("""CREATE TABLE IF NOT EXISTS email_verifications (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        code TEXT NOT NULL, expires_at REAL NOT NULL, used_at REAL)""")
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
    now = time.time()
    connection.execute(
        """INSERT INTO users (username, password_hash, name, surname, email, phone_number, role, active, email_verified, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?)""",
        (username, password_hash(password), 'Admin', 'Owner', f"{username}@example.com", '+1234567890', 'admin', now))


def public_user(row):
    keys = row.keys() if hasattr(row, 'keys') else []
    return {
        'id': row['id'],
        'username': row['username'],
        'name': row['name'] if 'name' in keys else '',
        'surname': row['surname'] if 'surname' in keys else '',
        'email': row['email'] if 'email' in keys else '',
        'phone_number': row['phone_number'] if 'phone_number' in keys else '',
        'role': row['role'],
        'active': bool(row['active']),
        'email_verified': bool(row['email_verified']) if 'email_verified' in keys else False,
        'created_at': row['created_at'] if 'created_at' in keys else 0,
    }


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


class CustomerRegistration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    surname: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=128)
    phone_number: str = Field(min_length=7, max_length=20)


class StaffCredentials(CustomerRegistration):
    pass


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class RequestCodeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username_or_email: str = Field(min_length=1, max_length=128)


class VerifyEmailRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username_or_email: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=128)


class InvitationRegistration(CustomerRegistration):
    token: str = Field(min_length=20, max_length=128)
    admin_passcode: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AccountState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active: bool | None = Field(default=None, strict=True)
    email_verified: bool | None = Field(default=None, strict=True)


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

    def create_verification_code(connection, user_id):
        code = f"{secrets.randbelow(1000000):06d}"
        expires = time.time() + 86400
        connection.execute('INSERT INTO email_verifications (user_id, code, expires_at) VALUES (?, ?, ?)',
                           (user_id, code, expires))
        return code

    def send_verification_email(email, code):
        print(f"[EMAIL SIMULATION] Sent verification code {code} to {email}")

    def create_user(connection, credentials, role):
        username = normalise_username(credentials.username)
        email = normalise_email(credentials.email)
        phone = normalise_phone(credentials.phone_number)
        validate_password(credentials.password)
        now = time.time()
        try:
            with connection:
                cursor = connection.execute(
                    """INSERT INTO users (username, password_hash, name, surname, email, phone_number, role, active, email_verified, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?)""",
                    (username, password_hash(credentials.password), credentials.name.strip(), credentials.surname.strip(),
                     email, phone, role, now)
                )
                user_id = cursor.lastrowid
                code = create_verification_code(connection, user_id)
                send_verification_email(email, code)
                user_row = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
                return public_user(user_row)
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, 'That username or email is unavailable.') from error

    @router.post('/auth/accept-invitation', status_code=201)
    def accept_invitation(body: InvitationRegistration, request: Request):
        username = normalise_username(body.username)
        email = normalise_email(body.email)
        phone = normalise_phone(body.phone_number)
        validate_password(body.password)

        expected_passcode = os.environ.get('TAKEAWAY_ADMIN_PASSCODE', 'AdminPass123!')
        if not secrets.compare_digest(body.admin_passcode, expected_passcode):
            raise HTTPException(401, 'Invalid admin passcode.')

        digest = hashlib.sha256(body.token.encode()).hexdigest()
        now = time.time()
        with closing(connect(request.app.state.database_path)) as connection:
            address = request.client.host if request.client else 'unknown'
            throttle(connection, [('accept-invite:' + address, 30)])
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                invitation = connection.execute("""SELECT i.id FROM admin_invitations i
                    JOIN users u ON u.id = i.created_by
                    WHERE i.token_hash = ? AND i.expires_at > ? AND i.used_at IS NULL
                    AND i.revoked = 0 AND u.active = 1 AND u.role = 'admin'""", (digest, now)).fetchone()
                if not invitation:
                    raise HTTPException(400, 'This invitation is invalid, expired, revoked or already used. Ask an administrator for a new link.')
                try:
                    cursor = connection.execute(
                        """INSERT INTO users (username, password_hash, name, surname, email, phone_number, role, active, email_verified, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, 'admin', 1, 0, ?)""",
                        (username, password_hash(body.password), body.name.strip(), body.surname.strip(), email, phone, now))
                except sqlite3.IntegrityError as error:
                    raise HTTPException(409, 'That username or email is unavailable. Choose another username; your invitation is still valid.') from error
                user_id = cursor.lastrowid
                code = create_verification_code(connection, user_id)
                send_verification_email(email, code)
                connection.execute('UPDATE admin_invitations SET used_at = ? WHERE id = ?', (now, invitation['id']))
                user_row = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
                return public_user(user_row)

    @router.post('/auth/register', status_code=201)
    def register(credentials: CustomerRegistration, request: Request):
        with closing(connect(request.app.state.database_path)) as connection:
            address = request.client.host if request.client else 'unknown'
            throttle(connection, [('register:' + address, 30)])
            return create_user(connection, credentials, 'customer')

    @router.post('/auth/request-verification-code')
    def request_verification_code(body: RequestCodeRequest, request: Request):
        identifier = body.username_or_email.strip().lower()
        with closing(connect(request.app.state.database_path)) as connection:
            address = request.client.host if request.client else 'unknown'
            throttle(connection, [('request-code:' + identifier, 10), ('request-code:' + address, 30)])
            user = connection.execute('SELECT * FROM users WHERE username = ? OR email = ?', (identifier, identifier)).fetchone()
            if not user:
                raise HTTPException(404, 'Account not found. Please check your email address or username.')
            if user['email_verified']:
                return {'sent': False, 'verified': True, 'message': 'Email address is already verified. You may sign in.'}
            with connection:
                code = create_verification_code(connection, user['id'])
                send_verification_email(user['email'], code)
            return {'sent': True, 'email': user['email'], 'username': user['username'],
                    'message': f"A verification code has been sent to {user['email']}."}

    @router.post('/auth/verify-email')
    def verify_email(body: VerifyEmailRequest, request: Request):
        identifier = body.username_or_email.strip().lower()
        with closing(connect(request.app.state.database_path)) as connection:
            user = connection.execute('SELECT * FROM users WHERE username = ? OR email = ?', (identifier, identifier)).fetchone()
            if not user:
                raise HTTPException(404, 'Account not found.')
            if user['email_verified']:
                return {'verified': True, 'message': 'Email is already verified.'}
            verification = connection.execute(
                """SELECT id FROM email_verifications
                   WHERE user_id = ? AND code = ? AND expires_at > ? AND used_at IS NULL
                   ORDER BY id DESC""",
                (user['id'], body.code.strip(), time.time())).fetchone()
            if not verification:
                raise HTTPException(400, 'Invalid or expired verification code.')
            with connection:
                connection.execute('UPDATE email_verifications SET used_at = ? WHERE id = ?', (time.time(), verification['id']))
                connection.execute('UPDATE users SET email_verified = 1 WHERE id = ?', (user['id'],))
            return {'verified': True, 'message': 'Email verified successfully. You may now sign in.'}

    @router.post('/auth/login')
    def login(credentials: LoginRequest, request: Request):
        identifier = credentials.username.strip().lower()
        with closing(connect(request.app.state.database_path)) as connection:
            address = request.client.host if request.client else 'unknown'
            throttle(connection, [('user:' + identifier, 10), ('login:' + address, 100)])
            user = connection.execute('SELECT * FROM users WHERE username = ? OR email = ?', (identifier, identifier)).fetchone()
            valid = password_matches(credentials.password, user['password_hash'] if user else '0' * 32 + ':' + '0' * 64)
            if not valid or not user or not user['active']:
                raise HTTPException(401, 'Incorrect username or password.')
            if not user['email_verified']:
                raise HTTPException(401, 'Email not verified. Please verify your email before signing in.')
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

    @router.delete('/auth/me')
    def delete_own_account(request: Request, user=Depends(require_account)):
        with closing(connect(request.app.state.database_path)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            if user['role'] == 'admin':
                admin_count = connection.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
                if admin_count <= 1:
                    raise HTTPException(409, 'Cannot delete the sole administrator account.')
            connection.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
            connection.execute('DELETE FROM email_verifications WHERE user_id = ?', (user['id'],))
            connection.execute('DELETE FROM users WHERE id = ?', (user['id'],))
        return {'deleted': True, 'message': 'Account deleted successfully.'}

    @router.post('/auth/logout')
    def logout(request: Request):
        authorization = request.headers.get('Authorization', '')
        token = authorization.partition(' ')[2]
        with closing(connect(request.app.state.database_path)) as connection, connection:
            connection.execute('DELETE FROM sessions WHERE token_hash = ?', (hashlib.sha256(token.encode()).hexdigest(),))
        return {'signed_out': True}

    @router.post('/auth/password')
    def change_password(body: PasswordChange, request: Request, user=Depends(require_account)):
        validate_password(body.new_password)
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
    def create_staff(credentials: StaffCredentials, request: Request):
        with closing(connect(request.app.state.database_path)) as connection:
            return create_user(connection, credentials, 'staff')

    @router.delete('/admin/users/{user_id}', dependencies=[Depends(require_admin)])
    def delete_user_account(user_id: int, request: Request):
        with closing(connect(request.app.state.database_path)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            target = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
            if not target:
                raise HTTPException(404, 'Account not found.')
            if target['role'] == 'admin':
                raise HTTPException(409, 'Administrator accounts cannot be deleted here.')
            connection.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
            connection.execute('DELETE FROM email_verifications WHERE user_id = ?', (user_id,))
            connection.execute('DELETE FROM users WHERE id = ?', (user_id,))
        return {'deleted': True, 'id': user_id}

    @router.patch('/admin/users/{user_id}', dependencies=[Depends(require_admin)])
    def update_user_state(user_id: int, body: AccountState, request: Request):
        with closing(connect(request.app.state.database_path)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            user = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
            if not user:
                raise HTTPException(404, 'Account not found.')
            if body.active is not None:
                if user['role'] == 'admin' and not body.active:
                    raise HTTPException(409, 'The administrator account cannot be disabled here.')
                connection.execute('UPDATE users SET active = ? WHERE id = ?', (int(body.active), user_id))
                if not body.active:
                    connection.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
            if body.email_verified is not None:
                connection.execute('UPDATE users SET email_verified = ? WHERE id = ?', (int(body.email_verified), user_id))
            updated = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        return public_user(updated)

    @router.patch('/admin/menu/{item_id}', dependencies=[Depends(require_admin)])
    def set_stock(item_id: int, body: StockUpdate, request: Request):
        with closing(connect(request.app.state.database_path)) as connection, connection:
            result = connection.execute('UPDATE products SET stock = ? WHERE id = ?', (body.stock, item_id))
            if not result.rowcount:
                raise HTTPException(404, 'Menu item not found.')
        return {'id': item_id, 'stock': body.stock}

    return router
