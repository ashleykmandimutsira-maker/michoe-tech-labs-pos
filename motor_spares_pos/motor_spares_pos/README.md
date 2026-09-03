# Motor Spares POS — Offline Sync and Admin Privileges

## Recent fixes

- Product create/update/archive/restore actions are queued for synchronization.
- Sales, stock movements, returns and refunds are queued locally.
- The POS never marks a record as synced unless the configured sync server acknowledges it.
- Automatic synchronization runs in the background at the configured interval.
- Product/price updates can be downloaded from the sync server.
- The Products archive filter now correctly shows archived records.
- Administrators can grant/revoke direct privileges for individual users from **Users → Manage privileges**.
- Sensitive product archive/restore operations remain ADMIN-only.
- **Live-updating screens.** Any change made anywhere in the system — a sale, a stock adjustment, a product edit, a spreadsheet import, or an update pulled from another terminal via sync — now refreshes whatever screen is currently open automatically, within about a second. Opening any screen also always shows current data instead of whatever was loaded at startup. (The POS/checkout screen is deliberately excluded so an in-progress sale is never disturbed.)
- **Local system time, consistently.** SQLite's built-in timestamp keyword is UTC, which previously didn't match the local timestamps used elsewhere in the app. Every timestamp the POS records now comes from the PC's own clock instead, applied centrally so it's automatically consistent everywhere. The Dashboard shows a live readout of the system clock so it's obvious what time the system is keyed off.
- **Inventory spreadsheet import/export.** See below.

## Inventory spreadsheet import/export

Available from **Inventory → Inventory spreadsheet**:

- **Download template** — a blank `.xlsx` with the right columns (Part No and Description are required; everything else is optional).
- **Import spreadsheet** — a data-entry clerk fills the template once (new stock, a stock count, price changes) and imports it. Existing products are matched by barcode, then part number, and updated; unmatched rows create new products. Quantity changes are recorded as proper audited stock movements, not silently overwritten, and everything is queued for synchronization exactly like a change made by hand in the POS — so it reaches every other terminal automatically. Requires the `ADD_STOCK` or `ADJUST_STOCK` permission (or admin).
- **Export full inventory** — any user can export the entire current catalog to `.xlsx` (cost prices are only included for users with `VIEW_COST_PRICE`). An admin can edit that file and re-import it through the same "Import spreadsheet" button to bulk-update the whole inventory in one go.

## Synchronization

The client expects these API endpoints:

- `GET /api/health`
- `POST /api/sync/push`
- `GET /api/sync/pull?shop_id=...&since=...`

Set the synchronization endpoint in **Settings** or `config.json`.

For development/testing, a small local HTTP server is included:

```powershell
python sync_server.py
```

The local development server listens on port `8765`. On another PC on the same LAN, set the client endpoint to the host PC's LAN address, for example `http://192.168.1.50:8765`.

This included server is for development/testing only. A production deployment should add authentication, TLS, backups, access control and a proper hosted database/API.

## Admin privileges

Log in as an administrator, open **Users**, select a user, and choose **Manage privileges**. Permissions are stored as direct user privileges and every grant/revoke is audited.

New users receive safe baseline permissions according to their selected role, which an administrator can then customize.

## Offline synchronization setup

The POS is local-first: sales, stock changes, product creates/updates, archives, returns, and refunds are written to SQLite first and placed in `sync_queue`.

When the configured sync endpoint is reachable, the application automatically attempts synchronization every 10 seconds. `Sync Now` performs the same operation immediately and only marks a queue item as `SYNCED` after the server acknowledges it.

### Local testing

1. Start the development sync server:
   - Windows: double-click `START_SYNC_SERVER.bat`, or run `python sync_server.py`.
2. In the POS open Settings and set **Sync endpoint** to:
   `http://127.0.0.1:8765`
3. Save settings.
4. Make or update a product.
5. Open Synchronization and use **Sync Now**, or wait for the automatic sync.
6. The queue should move from `PENDING` to `SYNCED`.

For a second PC on the same LAN, run the development server on the host PC and configure the other PC with the host's LAN address, for example `http://192.168.1.50:8765`. Windows Firewall must allow inbound TCP 8765. This development server is for testing only; production requires an authenticated HTTPS API, persistent server hosting, backups, and access control.

## Archived products

Products are soft-deleted by setting `active = 0`. In Products, enable **Show archived** to display archived items. After archiving a selected product, the view is automatically switched to show archived items so the admin can verify the `ARCHIVED` status. Restore is available for a selected archived product.

## Admin privileges

An active administrator can open Users, select a user, and choose **Manage privileges** to grant/revoke individual permissions. The administrator can also change another user's role. Product archive/restore remain administrator-only. Sensitive actions are audit logged.
