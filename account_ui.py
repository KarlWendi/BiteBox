"""Account sign-in, profile controls and administrator tools."""
import streamlit as st
import web_client
from web_client import APIError


def account_headers():
    session = st.session_state.get('account_session')
    return {'Authorization': 'Bearer ' + session['token']} if session else {}


def clear_account():
    for key in ('account_session', 'tracking_codes', 'staff_auth', 'staff_expires', 'trolley'):
        st.session_state.pop(key, None)


def show_account():
    st.subheader('Your account')
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
        st.write(f"Signed in as {user['username']} · {user['role'].title()}")
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
                    if not 12 <= len(new) <= 128:
                        st.error('Use a password between 12 and 128 characters.')
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
        with st.form('account_login', clear_on_submit=True):
            username = st.text_input('Account username')
            password = st.text_input('Account password', type='password')
            if st.form_submit_button('Sign in'):
                try:
                    session = web_client.request_api('POST', '/auth/login', json={'username': username, 'password': password})
                except APIError as error:
                    st.error(str(error))
                else:
                    st.session_state['account_session'] = session
                    st.session_state.pop('staff_auth', None)
                    st.session_state.pop('staff_expires', None)
                    st.rerun()
        with st.expander('Create a customer account'):
            with st.form('register_customer', clear_on_submit=True):
                username = st.text_input('Choose a username')
                password = st.text_input('Choose a password', type='password', help='Use at least 12 characters.')
                confirm = st.text_input('Confirm password', type='password')
                if st.form_submit_button('Create account'):
                    if not 12 <= len(password) <= 128:
                        st.error('Use a password between 12 and 128 characters.')
                    elif password != confirm:
                        st.error('The passwords do not match.')
                    else:
                        try:
                            web_client.request_api('POST', '/auth/register', json={'username': username, 'password': password})
                        except APIError as error:
                            st.error(str(error))
                        else:
                            st.session_state['account_notice'] = 'Account created. You can now sign in.'
                            st.rerun()


def show_admin():
    with st.expander('Administrator controls'):
        try:
            users = web_client.request_api('GET', '/admin/users', headers=account_headers())
            menu = web_client.request_api('GET', '/menu')
        except APIError as error:
            st.error(str(error))
            return
        st.subheader('Accounts')
        st.dataframe([{'Username': user['username'], 'Role': user['role'],
                       'Access': 'Active' if user['active'] else 'Disabled'} for user in users], hide_index=True)
        with st.form('create_staff', clear_on_submit=True):
            username = st.text_input('New staff username')
            password = st.text_input('Temporary staff password', type='password', help='At least 12 characters. Ask the staff member to change it after signing in.')
            if st.form_submit_button('Create staff account'):
                if not 12 <= len(password) <= 128:
                    st.error('Use a password between 12 and 128 characters.')
                    return
                try:
                    web_client.request_api('POST', '/admin/staff', headers=account_headers(), json={'username': username, 'password': password})
                except APIError as error:
                    st.error(str(error))
                else:
                    st.session_state['account_notice'] = 'Staff account created.'
                    st.rerun()
        for user in users:
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
