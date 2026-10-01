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


def normalise_username(username):
    username = username.strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,39}', username):
        raise HTTPException(422, 'Use 3–40 letters, numbers, dots, hyphens or underscores for your username.')
    return username


def initialise_accounts(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('customer', 'staff', 'admin')),
        active INTEGER NOT NULL DEFAULT 1)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        expires_at REAL NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS login_attempts (
        bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at REAL NOT NULL)""")
    username = os.environ.get('TAKEAWAY_ADMIN_USERNAME', '')
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
    connection.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
                       (username, password_hash(password), 'admin'))


def public_user(row):
    return {key: row[key] for key in ('id', 'username', 'role', 'active')}


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


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=128)


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

    def create_user(connection, credentials, role):
        username = normalise_username(credentials.username)
        try:
            with connection:
                cursor = connection.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
                                            (username, password_hash(credentials.password), role))
                return {'id': cursor.lastrowid, 'username': username, 'role': role, 'active': 1}
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, 'That username is unavailable.') from error

    @router.post('/auth/register', status_code=201)
    def register(credentials: Credentials, request: Request):
        with closing(connect(request.app.state.database_path)) as connection:
            address = request.client.host if request.client else 'unknown'
            throttle(connection, [('register:' + address, 30)])
            return create_user(connection, credentials, 'customer')

    @router.post('/auth/login')
    def login(credentials: LoginRequest, request: Request):
        username = normalise_username(credentials.username)
        with closing(connect(request.app.state.database_path)) as connection:
            address = request.client.host if request.client else 'unknown'
            throttle(connection, [('user:' + username, 10), ('login:' + address, 100)])
            user = connection.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            # Match the password work for unknown usernames to reduce timing disclosure.
            valid = password_matches(credentials.password, user['password_hash'] if user else '0' * 32 + ':' + '0' * 64)
            if not valid or not user or not user['active']:
                raise HTTPException(401, 'Incorrect username or password.')
            token = secrets.token_urlsafe(32)
            expires = time.time() + SESSION_SECONDS
            with connection:
                connection.execute('DELETE FROM sessions WHERE expires_at <= ?', (time.time(),))
                connection.execute('DELETE FROM login_attempts WHERE bucket = ?', ('user:' + username,))
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
