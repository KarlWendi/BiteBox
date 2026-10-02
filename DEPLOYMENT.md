# Stage 8: publish a public demo

Live website: https://takeaway-ordering-demo.onrender.com/

API address: https://takeaway-simulator-api.onrender.com/

Both services use the Free compute plan. TAKEAWAY_API_URL connects the website to the API; TAKEAWAY_TEMPORARY_DEMO=1 displays the shared temporary-data notice. Python 3.12.12 is configured for both services. Existing local data was not uploaded. All 34 automated tests passed before deployment.

On 16 September 2026, the public website loaded initial stock and accepted a two-burger order with a £7.98 confirmation and stock changing from 20 to 18.

The website and API need running Python servers. GitHub Pages only serves static files and cannot run these servers. The public website link belongs in the README after it has been deployed and checked.

## Two services, one visitor link

- Website: Streamlit runs website.py and presents the public interface.
- API: Uvicorn runs api:app and stores accepted orders in SQLite.
- TAKEAWAY_API_URL: an environment variable on the website tells it where the hosted API lives. localhost on a hosting server means that server, not your home computer.
- TAKEAWAY_DATABASE_PATH: optionally points the API at a database on persistent storage. When omitted, it uses restaurant.db beside database.py, as before.

## Staff login and private tracking

Set `TAKEAWAY_STAFF_USERNAME` and `TAKEAWAY_STAFF_PASSWORD` in the hosting service's secret environment settings. Choose a unique, randomly generated password of at least 16 characters. There is no default account: missing credentials or a shorter password keep staff routes locked. Never commit these values.

For the two-service setup, configure credentials on the **API**. When `TAKEAWAY_TEMPORARY_DEMO=1`, the website runs its API in-process, so configure credentials on the **website service** instead (and on any separately accessible API you still run). Restart the relevant service after changing secrets. Use HTTPS for both public services because staff authentication uses HTTP Basic over the server-to-server connection.

The legacy shared staff login remains available through the Staff tab. Credentials stay in that Streamlit session's server memory, with a one-hour UI login limit and explicit logout. Individual staff accounts are also available through the account controls described below.

## Customer and administrator accounts

### Invite another administrator

Sign in as an existing administrator, open **Your account → Administrator controls**, and select **Create admin invitation**. Copy the displayed link and share it privately with the intended administrator. The recipient opens the link, chooses their own username/password, and then signs in normally. Public registration remains customer-only.

Invitations expire after 24 hours and can be accepted once. Administrators can revoke pending invitations from the same screen. An unavailable username does not consume an invitation. The API stores only a hash of the token and atomically creates the account and consumes the invitation. Anyone holding an unused link can claim its admin access; share it only with the intended recipient. Do not post links publicly. The website removes the token from its visible URL after loading, but the initial URL may still exist in browser history or hosting logs.

`TAKEAWAY_WEBSITE_URL` on the website service controls the invitation-link destination. It defaults to `https://takeaway-ordering-demo.onrender.com/`; set it to your website address for another deployment or `http://localhost:8501` for local testing. Invitations belong to the API/database that issued them. Temporary demo storage resets invalidate invitations and remove created accounts. The first administrator still requires the Render bootstrap settings below.

Customers use **Don't have an account? Create one or sign in** at the top of the storefront to open the account page. After registering or signing in, **Back to your order** returns to the storefront with the trolley preserved. Signed-in visitors can reopen the page through **Your account**. Usernames contain 3–40 letters, numbers, dots, hyphens or underscores; passwords contain 12–128 characters. Signed-in users can view their own order history, change their password and sign out. Guest checkout and private tracking codes remain available. Guest orders are not automatically transferred to an account.

Before the first startup with accounts enabled, set these secret environment variables on the service running the API:

- `TAKEAWAY_ADMIN_USERNAME`: your chosen administrator username.
- `TAKEAWAY_ADMIN_PASSWORD`: a unique password of 16–128 characters.

For embedded demo mode (`TAKEAWAY_TEMPORARY_DEMO=1`), set them on the website service. For a separate API, set them on the API service. Deploy the updated website and API together. There is no default admin password and public registration always creates a customer.

Sign in through **Your account** using the administrator credentials. **Administrator controls** provides account access management, individual staff account creation and menu stock updates. The **Staff** tab provides kitchen order status controls for both staff and administrators.

| Role | Controls |
| --- | --- |
| Customer | Checkout, own order history, password change, sign out |
| Staff | Customer controls plus kitchen orders and queue |
| Administrator | Staff controls plus create staff, enable/disable non-admin accounts, replace product stock |

The initial administrator is created once. Restarts do not overwrite its password or create more administrators; use the signed-in password-change form to change the password. The admin account cannot be disabled in these controls. Store its password securely: there is no password recovery flow yet.

Passwords are salted and hashed. Login sessions expire after one hour; signing out revokes that session, and changing a password or disabling an account revokes all its sessions. Login attempts are rate limited. Permissions and order ownership are checked by the API, not just by hiding buttons.

Accounts and order history use the same SQLite database. `TAKEAWAY_DATABASE_PATH` selects its location; the parent directory must already exist and be writable. Use persistent storage to retain accounts across hosting restarts. The temporary public demo can lose accounts as well as orders when its storage resets.

Checkout returns a private random tracking code. Customers see only orders whose codes they hold, can save a code and enter it in a new session, and can remove an order from their session with Forget order. Codes are bearer secrets: anyone holding one can read that order. Only SHA-256 hashes are stored in SQLite; codes are sent in POST bodies, never URL query strings. Order responses use `Cache-Control: no-store`. Lost codes cannot be recovered; orders from before this update remain visible to staff only. Demo resets also remove tracked orders.

`GET /orders`, `GET /queue`, `GET /staff/session`, and `PATCH /orders/{id}/status` require staff authentication. `POST /orders`, `POST /checkout`, `GET /menu`, and `POST /track` remain public; `/track` requires the private code. In API docs, use Authorize to supply staff credentials when testing protected routes.

## Storage

A free disposable demo can recreate its fictional database after server restarts. It must say clearly that data is temporary. A persistent version needs durable database storage. Render's persistent disks require a paid service; do not create paid resources without reviewing and accepting the cost.

Existing local restaurant.db is never uploaded. The public demo begins with fictional initial stock. All visitors would share this demo inventory unless a later stage adds separate visitor sessions.

## Render setup

Create two Python web services from this GitHub repository. For both, use the build command `pip install -r requirements.txt` and a supported Python version matching the tested workflow.

API start command:

```text
uvicorn api:app --host 0.0.0.0 --port $PORT
```

Set the API health-check path to `/`. Once the API is running, copy its HTTPS service address.

Website start command:

```text
streamlit run website.py --server.address 0.0.0.0 --server.port $PORT --server.headless true --browser.gatherUsageStats false
```

Set TAKEAWAY_API_URL on the website to the API's HTTPS address, without a trailing slash. Set its health-check path to `/_stcore/health`. Do not enter the local 127.0.0.1 address. Keep Streamlit's default browser security protections enabled.

For durable SQLite, attach a persistent disk to the API only and point TAKEAWAY_DATABASE_PATH at a file under its mount path, such as /var/data/restaurant.db. Keep a single API instance with this SQLite database.

## Before adding the live link

Open the website's public HTTPS address in a separate browser session. Confirm the menu loads, submit one fictional order, check the confirmation and stock, then refresh and change station counts without creating another order. Check unavailable stock rejection. Verify restart behaviour agrees with the chosen storage model. Only then add a `Try the live demo` link to README.md and the GitHub repository's Website field.

Signing up, authorising GitHub access and accepting hosting costs require the account owner. No public URL is available until the provider has successfully deployed both services.

References: [Render web services](https://render.com/docs/web-services), [persistent disks](https://render.com/docs/disks).
