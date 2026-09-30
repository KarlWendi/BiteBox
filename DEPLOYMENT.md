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

Staff sign in through the Staff tab. Credentials stay in that Streamlit session's server memory, with a one-hour UI login limit and explicit logout; they are supplied on each privileged request and are never cached globally. Changing the configured password revokes the previous credentials. This is a single shared staff account, not individual staff accounts or roles.

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
