"""Adapt libSQL's tuple rows and errors to the application's SQLite interface."""
import os
import sqlite3
from collections.abc import Mapping
from urllib.parse import urlsplit


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except ValueError as error:
        # libsql reports database errors as ValueError. Never expose credentials
        # or remote response bodies in application exceptions.
        if 'constraint failed' in str(error).lower():
            raise sqlite3.IntegrityError('Database constraint failed.') from None
        raise sqlite3.OperationalError('Database is unavailable. Please try again.') from None


class Row(Mapping):
    def __init__(self, columns, values):
        self.columns, self.values = columns, values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.values[key]
        return self.values[self.columns.index(key)]

    def __iter__(self):
        return iter(self.columns)

    def __len__(self):
        return len(self.columns)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = cursor.lastrowid
        self.rowcount = cursor.rowcount
        self.columns = [column[0] for column in (cursor.description or [])]
        self.done = False

    def fetchone(self):
        if self.done:
            return None
        values = call(self.cursor.fetchone)
        self.done = values is None
        return None if values is None else Row(self.columns, values)

    def fetchall(self):
        return list(self)

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row


class Connection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        return Cursor(call(self.connection.execute, sql, parameters))

    def commit(self):
        call(self.connection.commit)

    def rollback(self):
        call(self.connection.rollback)

    def close(self):
        call(self.connection.close)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            self.rollback()
        else:
            try:
                self.commit()
            except Exception:
                self.rollback()
                raise
        return False


def connect_libsql(database, remote=True):
    token = ''
    if remote:
        url = urlsplit(str(database))
        if url.scheme not in ('libsql', 'https') or not url.hostname or url.username or url.password:
            raise RuntimeError('Use a secure Turso database URL.')
        token = os.environ.get('TURSO_AUTH_TOKEN', '')
        if not token:
            raise RuntimeError('TURSO_AUTH_TOKEN must be configured for remote storage.')
    try:
        import libsql
    except ImportError:
        raise RuntimeError('The libsql driver is required; use the Linux deployment environment.') from None
    connection = Connection(call(libsql.connect, str(database), auth_token=token, timeout=15))
    connection.execute('PRAGMA foreign_keys = ON')
    return connection
