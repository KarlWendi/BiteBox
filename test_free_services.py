"""Free-provider boundary tests. No real emails or hosted data are touched."""
import os
import sqlite3
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException
from account_email import send_email
from remote_database import Connection, call, connect_libsql


class FreeServiceTests(unittest.TestCase):
    def test_rows_transactions_and_saved_insert_id(self):
        db = Connection(sqlite3.connect(':memory:'))
        self.addCleanup(db.close)
        db.execute('CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
        with db:
            cursor = db.execute('INSERT INTO sample(name) VALUES (?)', ('saved',))
        with self.assertRaises(RuntimeError):
            with db:
                db.execute('INSERT INTO sample(name) VALUES (?)', ('rolled back',))
                raise RuntimeError('cancel')
        rows = db.execute('SELECT * FROM sample').fetchall()
        self.assertEqual([dict(row) for row in rows], [{'id': 1, 'name': 'saved'}])
        self.assertEqual(rows[0][0], cursor.lastrowid)
        self.assertEqual(cursor.rowcount, 1)

    def test_errors_do_not_expose_remote_details(self):
        with self.assertRaises(sqlite3.IntegrityError):
            call(Mock(side_effect=ValueError('UNIQUE constraint failed: users.email')))
        with self.assertRaises(sqlite3.OperationalError) as result:
            call(Mock(side_effect=ValueError('network failure secret-token')))
        self.assertNotIn('secret-token', str(result.exception))

    def test_missing_token_and_insecure_url_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                connect_libsql('libsql://test.turso.io')
            with self.assertRaises(RuntimeError):
                connect_libsql('http://test.turso.io')

    def test_brevo_accepted_and_rejected_messages(self):
        settings = {'TAKEAWAY_EMAIL_PROVIDER': 'brevo', 'BREVO_API_KEY': 'test-key',
                    'TAKEAWAY_EMAIL_FROM': 'sender@example.test',
                    'TAKEAWAY_WEBSITE_URL': 'https://bitebox.example.test'}
        with patch.dict(os.environ, settings, clear=True), patch('account_email.httpx.post') as post:
            request = httpx.Request('POST', 'https://api.brevo.com/v3/smtp/email')
            post.return_value = httpx.Response(201, json={'messageId': 'accepted'}, request=request)
            send_email('customer@example.test', 'verify', 'example-token')
            self.assertIn('verify_account=example-token', post.call_args.kwargs['json']['textContent'])
            self.assertEqual(post.call_args.kwargs['headers']['api-key'], 'test-key')
            for response in (httpx.Response(429, request=request),
                             httpx.Response(201, json={}, request=request)):
                post.return_value = response
                with self.assertRaises(HTTPException) as result:
                    send_email('customer@example.test', 'reset', 'example-token')
                self.assertEqual(result.exception.status_code, 503)
