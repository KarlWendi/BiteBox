"""Account sign-in, profile controls and administrator tools."""
import streamlit as st
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
import web_client
from web_client import APIError


def account_headers():
    session = st.session_state.get('account_session')
    return {'Authorization': 'Bearer ' + session['token']} if session else {}


def clear_account():
    for key in ('account_session', 'tracking_codes', 'staff_auth', 'staff_expires', 'trolley', 'created_invitation', 'admin_invite_token'):
        st.session_state.pop(key, None)


def valid_registration(username, password, confirm, name, surname, email, phone_number):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,39}', username.strip().lower()):
        st.error('Choose a username with 3–40 characters. Start with a letter or number; use only letters, numbers, dots, hyphens or underscores.')
        return False
    if not name.strip() or not surname.strip():
        st.error('Please enter your first name and surname.')
        return False
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email.strip().lower()):
        st.error('Please enter a valid email address.')
        return False
    if not re.fullmatch(r'\+?[0-9\s\-\(\)]{7,20}', phone_number.strip()):
        st.error('Please enter a valid phone number.')
        return False
    if not (8 <= len(password) <= 128):
        st.error('Use a password between 8 and 128 characters.')
        return False
    if not re.search(r'[A-Z]', password):
        st.error('Password must contain at least one uppercase letter.')
        return False
    if not re.search(r'[a-z]', password):
        st.error('Password must contain at least one lowercase letter.')
        return False
    if not re.search(r'[0-9]', password):
        st.error('Password must contain at least one digit.')
        return False
    if not re.search(r'[^a-zA-Z0-9]', password):
        st.error('Password must contain at least one special character.')
        return False
    if password != confirm:
        st.error('The passwords do not match.')
        return False
    return True


def show_email_verification():
    st.subheader('Verify your email')
    st.caption('Enter your registered username or email address and the verification code.')

    prefilled_identifier = st.session_state.get('pending_verification_user', '')
    prefilled_code = st.session_state.get('pending_verification_code', '')
    if prefilled_code:
        st.info(f"Your verification code is: {prefilled_code}")

    with st.form('verify_email_form'):
        identifier = st.text_input('Username or Email address', value=prefilled_identifier)
        code = st.text_input('Verification code', value=prefilled_code)
        if st.form_submit_button('Verify Email'):
            try:
                res = web_client.request_api('POST', '/auth/verify-email', json={
                    'username_or_email': identifier,
                    'code': code
                })
            except APIError as error:
                st.error(str(error))
            else:
                st.session_state.pop('pending_verification_user', None)
                st.session_state.pop('pending_verification_code', None)
                st.session_state['account_notice'] = res.get('message', 'Email verified successfully. You may now sign in.')
                st.session_state['account_page'] = True
                st.rerun()
    if st.button('Back to sign in', type='tertiary'):
        st.session_state.pop('pending_verification_user', None)
        st.session_state.pop('pending_verification_code', None)
        st.session_state['account_page'] = True
        st.rerun()


def show_account():
    notice = st.session_state.pop('account_notice', None)
    if notice:
        st.success(notice)
    session = st.session_state.get('account_session')
    if session:
        try:
            user = web_client.request_api('GET', '/auth/me', headers=account_headers())
        except APIError as error:
            st.error(str(error))
            # Do not downgrade to a guest checkout after a service failure.
            if st.button('Clear sign-in on this device'):
                clear_account()
                st.rerun()
            return
        session['user'] = user
        st.write(f"Signed in as **{user['name']} {user['surname']}** (@{user['username']}) · {user['role'].title()}")
        st.caption(f"Email: {user['email']} · Phone: {user['phone_number']}")
        if st.button('Sign out'):
            try:
                web_client.request_api('POST', '/auth/logout', headers=account_headers())
            except APIError as error:
                st.error(str(error))
            else:
                clear_account()
                st.rerun()
        with st.expander('Change password'):
            with st.form('change_password', clear_on_submit=True):
                current = st.text_input('Current password', type='password')
                new = st.text_input('New password', type='password')
                confirm = st.text_input('Confirm new password', type='password')
                if st.form_submit_button('Update password'):
                    if not (8 <= len(new) <= 128):
                        st.error('Use a password between 8 and 128 characters.')
                    elif new != confirm:
                        st.error('The new passwords do not match.')
                    else:
                        try:
                            web_client.request_api('POST', '/auth/password', headers=account_headers(),
                                                   json={'current_password': current, 'new_password': new})
                        except APIError as error:
                            st.error(str(error))
                        else:
                            clear_account()
                            st.session_state['account_notice'] = 'Password updated. Please sign in again.'
                            st.rerun()
        if user['role'] == 'admin':
            show_admin()
    else:
        st.caption('Sign in for saved order history. Staff and administrators can sign in here too, or you can order as a guest.')
        with st.form('account_login'):
            username = st.text_input('Account username or email')
            password = st.text_input('Account password', type='password')
            if st.form_submit_button('Sign in'):
                try:
                    session = web_client.request_api('POST', '/auth/login', json={'username': username, 'password': password})
                except APIError as error:
                    st.error(str(error))
                    if 'Email not verified' in str(error):
                        st.session_state['pending_verification_user'] = username
                else:
                    st.session_state['account_session'] = session
                    st.session_state.pop('staff_auth', None)
                    st.session_state.pop('staff_expires', None)
                    st.rerun()
        if st.button('Need to verify your email?', type='tertiary'):
            st.session_state['account_page'] = 'verify'
            st.rerun()
        st.caption('New administrator? Ask an existing administrator for an invitation link. Public registration creates a customer account.')
        if st.button("Don't have an account? Create a customer account", type='tertiary'):
            st.session_state['account_page'] = 'register'
            st.rerun()


def show_registration():
    st.caption('Create an account to save your order history.')
    if st.button('Already have an account? Sign in', type='tertiary'):
        st.session_state['account_page'] = True
        st.rerun()
    st.caption('Username: 3–40 letters/numbers/dots/hyphens. Password: 8–128 characters with upper, lower, digit and special char.')
    with st.form('register_customer'):
        name = st.text_input('First name')
        surname = st.text_input('Surname')
        email = st.text_input('Email address')
        phone_number = st.text_input('Phone number')
        username = st.text_input('Choose a username')
        password = st.text_input('Choose a password', type='password', help='At least 8 characters with upper, lower, number, special char.')
        confirm = st.text_input('Confirm password', type='password')
        if st.form_submit_button('Create account'):
            if valid_registration(username, password, confirm, name, surname, email, phone_number):
                try:
                    res = web_client.request_api('POST', '/auth/register', json={
                        'username': username, 'password': password,
                        'name': name.strip(), 'surname': surname.strip(),
                        'email': email.strip(), 'phone_number': phone_number.strip()
                    })
                except APIError as error:
                    st.error(str(error))
                else:
                    st.session_state['pending_verification_user'] = username
                    st.session_state['pending_verification_code'] = res.get('verification_code', '')
                    st.session_state['account_page'] = 'verify'
                    st.session_state['account_notice'] = f"Account created! Your verification code is {res.get('verification_code', '')}. Please verify your email to activate your account."
                    st.rerun()


def show_admin():
    with st.expander('Administrator controls'):
        show_invitations()
        try:
            users = web_client.request_api('GET', '/admin/users', headers=account_headers())
            menu = web_client.request_api('GET', '/menu')
        except APIError as error:
            st.error(str(error))
            return
        st.subheader('Accounts')
        st.dataframe([{
            'Name': f"{user.get('name', '')} {user.get('surname', '')}".strip() or '—',
            'Username': user['username'],
            'Email': user.get('email', '') or '—',
            'Phone': user.get('phone_number', '') or '—',
            'Role': user['role'].title(),
            'Verified': 'Yes' if user.get('email_verified') else 'No',
            'Access': 'Active' if user['active'] else 'Disabled'
        } for user in users], hide_index=True)
        with st.form('create_staff', clear_on_submit=True):
            st.caption('Create a new staff account.')
            name = st.text_input('First name', key='staff_name')
            surname = st.text_input('Surname', key='staff_surname')
            email = st.text_input('Email address', key='staff_email')
            phone_number = st.text_input('Phone number', key='staff_phone')
            username = st.text_input('New staff username', key='staff_username')
            password = st.text_input('Temporary staff password', type='password', help='At least 8 chars with upper, lower, digit and special char.')
            confirm = st.text_input('Confirm staff password', type='password')
            if st.form_submit_button('Create staff account'):
                if valid_registration(username, password, confirm, name, surname, email, phone_number):
                    try:
                        res = web_client.request_api('POST', '/admin/staff', headers=account_headers(), json={
                            'username': username, 'password': password,
                            'name': name.strip(), 'surname': surname.strip(),
                            'email': email.strip(), 'phone_number': phone_number.strip()
                        })
                    except APIError as error:
                        st.error(str(error))
                    else:
                        code = res.get('verification_code', '')
                        st.session_state['account_notice'] = f"Staff account created! Verification code is {code}."
                        st.rerun()

        for user in users:
            if not user.get('email_verified'):
                if st.button(f"Verify email for {user['username']}", key=f"verify-email-{user['id']}"):
                    try:
                        web_client.request_api('PATCH', f"/admin/users/{user['id']}", headers=account_headers(), json={'email_verified': True})
                    except APIError as error:
                        st.error(str(error))
                    else:
                        st.session_state['account_notice'] = f"Email verified for {user['username']}."
                        st.rerun()
            if user['role'] == 'admin':
                continue
            action = 'Disable' if user['active'] else 'Enable'
            if st.button(f"{action} {user['username']}", key=f"access-{user['id']}"):
                try:
                    web_client.request_api('PATCH', f"/admin/users/{user['id']}", headers=account_headers(), json={'active': not bool(user['active'])})
                except APIError as error:
                    st.error(str(error))
                else:
                    st.rerun()
        st.subheader('Stock')
        by_id = {item['id']: item for item in menu}
        if not by_id:
            st.info('No menu items are available to manage.')
            return
        item_id = st.selectbox('Product to update', list(by_id), format_func=lambda value: by_id[value]['name'])
        with st.form(f'manage_stock_{item_id}'):
            quantity = st.number_input('New available stock', min_value=0, max_value=10000,
                                       value=by_id[item_id]['stock'], key=f'stock-{item_id}')
            st.caption('This replaces the available quantity for the selected product.')
            if st.form_submit_button('Update stock'):
                try:
                    web_client.request_api('PATCH', f'/admin/menu/{item_id}', headers=account_headers(), json={'stock': quantity})
                except APIError as error:
                    st.error(str(error))
                else:
                    st.session_state['account_notice'] = 'Stock updated.'
                    st.rerun()


def show_invitations():
    st.subheader('Invite an administrator')
    st.caption('Anyone with this link can create an administrator account. Share it privately with your intended recipient. It expires after 24 hours and works once.')
    if st.button('Create admin invitation'):
        try:
            st.session_state['created_invitation'] = web_client.request_api('POST', '/admin/invitations', headers=account_headers())
        except APIError as error:
            st.error(str(error))
    created = st.session_state.get('created_invitation')
    try:
        invitations = web_client.request_api('GET', '/admin/invitations', headers=account_headers())
    except APIError as error:
        st.error(str(error))
        return
    if created and not any(i['id'] == created['id'] and not i['used_at'] and not i['revoked'] and i['expires_at'] > time.time() for i in invitations):
        st.session_state.pop('created_invitation', None)
        created = None
    if created:
        base = os.environ.get('TAKEAWAY_WEBSITE_URL', 'https://takeaway-ordering-demo.onrender.com/').rstrip('/') + '/'
        st.code(base + '?' + urlencode({'admin_invite': created['token']}), language=None)
        st.caption('Copy this link now. It is not recoverable after you sign out.')
    for invitation in invitations:
        if invitation['used_at'] or invitation['revoked'] or invitation['expires_at'] <= time.time():
            continue
        expires = datetime.fromtimestamp(invitation['expires_at'], timezone.utc).strftime('%d %b %Y %H:%M UTC')
        st.caption(f"Invitation #{invitation['id']} · expires {expires}")
        if st.button(f"Revoke invitation #{invitation['id']}"):
            try:
                web_client.request_api('DELETE', f"/admin/invitations/{invitation['id']}", headers=account_headers())
            except APIError as error:
                st.error(str(error))
            else:
                if created and created['id'] == invitation['id']:
                    st.session_state.pop('created_invitation', None)
                st.rerun()


def show_invitation_registration():
    st.title('Create your administrator account')
    st.caption('Use the invitation link and admin passcode to create your administrator sign-in. Username: 3–40 letters/numbers/dots/hyphens. Password: 8–128 characters with upper, lower, digit and special char.')
    if st.session_state.get('account_session'):
        st.info('You are already signed in. Sign out below to create a separate administrator account. Your invitation will stay open.')
        if st.button('Sign out and continue with invitation'):
            try:
                web_client.request_api('POST', '/auth/logout', headers=account_headers())
            except APIError as error:
                st.error(str(error))
            else:
                token = st.session_state['admin_invite_token']
                clear_account()
                st.session_state['admin_invite_token'] = token
                st.rerun()
    else:
        with st.form('accept_admin_invitation'):
            name = st.text_input('First name')
            surname = st.text_input('Surname')
            email = st.text_input('Email address')
            phone_number = st.text_input('Phone number')
            username = st.text_input('Admin username')
            admin_passcode = st.text_input('Admin passcode', type='password')
            password = st.text_input('Admin password', type='password')
            confirm = st.text_input('Confirm admin password', type='password')
            if st.form_submit_button('Create administrator account'):
                if not admin_passcode.strip():
                    st.error('Please enter the admin passcode.')
                elif valid_registration(username, password, confirm, name, surname, email, phone_number):
                    try:
                        res = web_client.request_api('POST', '/auth/accept-invitation', json={
                            'username': username, 'password': password,
                            'name': name.strip(), 'surname': surname.strip(),
                            'email': email.strip(), 'phone_number': phone_number.strip(),
                            'admin_passcode': admin_passcode.strip(),
                            'token': st.session_state['admin_invite_token']})
                    except APIError as error:
                        st.error(str(error))
                    else:
                        st.session_state.pop('admin_invite_token', None)
                        st.session_state['pending_verification_user'] = username
                        st.session_state['pending_verification_code'] = res.get('verification_code', '')
                        st.session_state['account_page'] = 'verify'
                        st.session_state['account_notice'] = f"Administrator account created! Your verification code is {res.get('verification_code', '')}. Please verify your email to activate your account."
                        st.rerun()
    if st.button('Return to sign in', type='tertiary'):
        st.session_state.pop('admin_invite_token', None)
        st.session_state['account_page'] = True
        st.rerun()
