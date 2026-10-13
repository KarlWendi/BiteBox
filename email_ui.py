"""Verification, recovery and legacy-account email screens."""
import streamlit as st
import web_client
from web_client import APIError


def email_available():
    try:
        return web_client.request_api('GET', '/auth/options')['email_enabled']
    except APIError as error:
        st.error(str(error))
        st.stop()


def recovery_forms():
    if not email_available():
        return
    with st.expander('Forgot password or need a verification email?'):
        with st.form('request_account_email'):
            email = st.text_input('Your email address')
            reset = st.form_submit_button('Send password reset email')
            verify = st.form_submit_button('Resend verification email')
            if reset or verify:
                path = '/auth/forgot-password' if reset else '/auth/resend-verification'
                try:
                    result = web_client.request_api('POST', path, json={'email': email.strip()})
                except APIError as error:
                    st.error(str(error))
                else:
                    st.success(result['message'])


def recovery_address(user, headers):
    if not email_available():
        return
    if user.get('email_verified'):
        st.caption(f"Verified email: {user['email']}")
        return
    with st.expander('Add a verified email for password recovery'):
        st.caption('Existing accounts can keep their username. Verify an email address so you can reset a forgotten password.')
        with st.form('attach_account_email'):
            email = st.text_input('Recovery email address', value=user.get('email') or '')
            password = st.text_input('Confirm current password', type='password')
            if st.form_submit_button('Send verification email'):
                try:
                    result = web_client.request_api('POST', '/auth/email', headers=headers,
                                                    json={'email': email.strip(), 'password': password})
                except APIError as error:
                    st.error(str(error))
                else:
                    st.success(result['message'])


def show_email_link():
    from account_ui import clear_account
    kind, token = st.session_state['email_link']
    st.title('Verify your email' if kind == 'verify' else 'Reset your password')
    st.caption('Confirm below to use your private, single-use email link.')
    with st.form('consume_account_email'):
        password = confirm = ''
        if kind == 'reset':
            password = st.text_input('New password', type='password', help='Use 12–128 characters.')
            confirm = st.text_input('Confirm new password', type='password')
        if st.form_submit_button('Verify email' if kind == 'verify' else 'Reset password'):
            if kind == 'reset' and not 12 <= len(password) <= 128:
                st.error('Use a password between 12 and 128 characters.')
            elif kind == 'reset' and password != confirm:
                st.error('The passwords do not match.')
            else:
                try:
                    body = {'token': token}
                    if kind == 'reset':
                        body['password'] = password
                    result = web_client.request_api('POST', '/auth/verify-email' if kind == 'verify' else '/auth/reset-password', json=body)
                except APIError as error:
                    st.error(str(error))
                else:
                    if kind == 'reset':
                        clear_account()
                    st.session_state.pop('email_link', None)
                    st.session_state['account_page'] = True
                    st.session_state['account_notice'] = result['message']
                    st.rerun()
    if st.button('Return to sign in or request a new link', type='tertiary'):
        st.session_state.pop('email_link', None)
        st.session_state['account_page'] = True
        st.rerun()
