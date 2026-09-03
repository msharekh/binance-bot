# Binance Bot Hosting Plan (Render)

## 1. Goal

Host the project on Render with:

- An always-running trading worker (`app.py`).
- A browser-accessible Streamlit dashboard (`dashboard.py`).
- Persistent and shared state.
- Protected credentials and dashboard access.
- Safe deployment, monitoring, backup, and rollback procedures.

This is a real-money system when `ENABLE_TRADING=true`. The first hosted deployment must use Binance testnet and trading must remain disabled until every acceptance test passes.

## 2. Recommended Architecture

Use three Render resources:

1. **Web service — dashboard**
   - Runs Streamlit.
   - Reads status and positions from PostgreSQL.
   - Writes configuration changes and manual commands to PostgreSQL.
   - Does not hold Binance trading credentials.

2. **Background worker — trading bot**
   - Runs `app.py` continuously.
   - Holds the Binance API credentials.
   - Is the only process allowed to submit Binance orders.
   - Reads configuration/manual commands and writes status, positions, and transactions.

3. **Managed PostgreSQL database**
   - Replaces the JSON files used for communication and persistence.
   - Allows the dashboard and worker to share consistent state.
   - Survives application deployments and restarts.

Do not deploy the current dashboard and worker as separate services while continuing to use local JSON files. Their filesystems are isolated, and a disk attached to one service is not a shared filesystem for the other service.

## 3. Why PostgreSQL Is Required

The project currently uses these local files:

- `bot_config.json`
- `bot_status.json`
- `live_prices.json`
- `trade_state.json`
- `transactions.jsonl`
- `entry_cooldowns.json`
- `buy_requests.jsonl`
- `sell_requests.jsonl`
- `market_overview_history.jsonl`
- `ai_brief.json`
- `bot.lock`

This works locally because both processes use the same directory. In hosted production, PostgreSQL should become the single source of truth.

Suggested tables:

| Table | Purpose |
|---|---|
| `bot_config` | One active configuration row with revision and update time |
| `bot_status` | Latest heartbeat, account summary, environment, and bot state |
| `market_status` | Latest analysis and live price per symbol |
| `positions` | Open tracked positions, entry, quantity, SL, TP, and timestamps |
| `transactions` | Immutable buy/sell history, P&L, reason, order ID, and fees |
| `manual_commands` | Manual buy, market sell, and sell-price requests |
| `entry_cooldowns` | Last entry candle used per symbol |
| `market_history` | Optional market overview samples with retention policy |
| `ai_briefs` | Optional generated AI summaries |
| `worker_lease` | Single-worker ownership and heartbeat |

Manual commands should have `command_id`, `action`, `symbol`, payload, environment, creation time, expiry time, status, processing time, completion time, and result/error fields.

The worker should claim commands inside a database transaction. `command_id` must be unique so a restart cannot replay a real order.

## 4. Required Code Changes

### Phase A — storage layer

Create a storage module with functions such as:

- `load_config()` / `save_config()`
- `load_positions()` / `save_position()` / `close_position()`
- `save_status()` / `save_market_status()`
- `record_transaction()`
- `enqueue_command()` / `claim_next_command()` / `complete_command()`
- `load_entry_cooldowns()` / `save_entry_cooldown()`
- `acquire_worker_lease()` / `renew_worker_lease()`

Use `DATABASE_URL` and connection pooling. Apply schema migrations during deployment, not from both running services simultaneously.

### Phase B — worker safety

- Replace the Windows `msvcrt` file lock with a PostgreSQL worker lease or advisory lock.
- Enforce one trading worker instance.
- Preserve the existing command expiry and environment checks.
- Use unique client order IDs derived from `command_id` where Binance supports them.
- Mark a command complete only after recording the Binance response.
- Reconcile uncertain orders with Binance before retrying after a timeout.
- Keep position/exposure checks in the worker, never only in the dashboard.
- Continue monitoring open positions even when a symbol is removed from targets.

### Phase C — dashboard

- Replace JSON reads/writes with database queries.
- Show command states: queued, processing, filled, rejected, expired, or failed.
- Display the worker heartbeat and make stale/offline state prominent.
- Disable manual buy/sell buttons when the worker is stale.
- Keep Binance credentials out of the web service.
- Add authentication before exposing the dashboard publicly.

### Phase D — exact fees

The current dashboard estimates fees. For exact figures, save every fill's `commission` and `commissionAsset` from Binance order responses. If a USDT total is required, also save the conversion rate and conversion timestamp rather than silently treating every commission asset as USDT.

## 5. Dashboard Security

Do not publish the current dashboard without access control because it contains controls that can create real orders.

Recommended controls:

- Put the dashboard behind an identity-aware access layer such as Cloudflare Access, or implement a properly reviewed login system.
- Require HTTPS only.
- Use a long, unique session secret.
- Allow only named users.
- Add CSRF-safe confirmation for state-changing commands.
- Rate-limit manual order requests.
- Record an audit event for every configuration change and manual command.
- Never display API secrets in logs, errors, status JSON, or the UI.

## 6. Binance API Key Safety

Create a dedicated API key for the hosted bot:

- Enable Spot trading only.
- Disable withdrawals.
- Do not reuse a personal/master API key.
- Apply IP restrictions if compatible with the selected Render networking plan.
- Verify Render's current outbound IP behavior before setting the Binance allowlist.
- Start with Binance testnet credentials.
- Rotate the key immediately if it appears in source control, logs, screenshots, or support messages.

The dashboard service should not receive `BINANCE_API_KEY` or `BINANCE_API_SECRET`. Only the worker needs them.

## 7. Render Environment Variables

### Worker secrets

```text
DATABASE_URL=<provided by Render>
BINANCE_API_KEY=<secret>
BINANCE_API_SECRET=<secret>
BINANCE_TESTNET=true
ENABLE_TRADING=false
```

Optional worker settings:

```text
TRADE_AMOUNT_USDT=20
MAX_TOTAL_EXPOSURE_USDT=100
MAX_OPEN_POSITIONS=5
```

### Dashboard secrets

```text
DATABASE_URL=<provided by Render>
APP_SESSION_SECRET=<secret>
```

Optional AI advisor variables belong only on the service that generates the brief:

```text
ENABLE_AI_ADVISOR=false
OPENAI_API_KEY=<secret>
OPENAI_MODEL=<chosen model>
```

Do not put secrets in `render.yaml`, `.env`, Git history, or Markdown documentation.

## 8. Service Commands

Dashboard build command:

```bash
pip install -r requirements.txt
```

Dashboard start command:

```bash
streamlit run dashboard.py --server.address 0.0.0.0 --server.port $PORT --server.headless true
```

Worker build command:

```bash
pip install -r requirements.txt
```

Worker start command:

```bash
python -u app.py
```

Add the PostgreSQL driver and migration tool to `requirements.txt` during the storage refactor. Pin dependency versions before production deployment.

## 9. Blueprint Structure

After the database refactor, create a `render.yaml` Blueprint containing:

- One Python web service for Streamlit.
- One Python background worker for `app.py`.
- One managed PostgreSQL database.
- `DATABASE_URL` references for both services.
- Worker-only Binance secrets entered through the Render dashboard.
- Health-check path for the web service.
- A migration command or pre-deploy command.
- Explicit production branch and auto-deploy policy.

Do not enable automatic production trading merely because a deployment succeeds.

## 10. Deployment Sequence

### Stage 1 — local migration

1. Back up all current JSON/JSONL state files.
2. Add database models and migrations.
3. Add an import command that migrates existing configuration, positions, transactions, and cooldowns.
4. Test the storage layer locally with a temporary PostgreSQL database.
5. Verify that duplicate `command_id` values cannot create duplicate orders.

### Stage 2 — hosted analysis only

1. Create Render PostgreSQL.
2. Deploy the dashboard and worker with `ENABLE_TRADING=false`.
3. Confirm database migrations completed once.
4. Confirm the worker heartbeat updates.
5. Confirm market cards and live prices refresh.
6. Confirm dashboard configuration changes reach the worker.
7. Confirm manual commands are rejected while trading is disabled.

### Stage 3 — Binance testnet

1. Set `BINANCE_TESTNET=true`.
2. Set `ENABLE_TRADING=true` only after checking every exposure setting.
3. Test automatic buy, manual buy, automatic TP/SL/RSI exit, manual market sell, and custom sell price.
4. Restart the worker during queued and open trades to test recovery.
5. Verify no command or order is duplicated.
6. Verify open positions remain monitored after target removal.

### Stage 4 — restricted production pilot

1. Back up the database.
2. Change to the dedicated production Binance key.
3. Keep trading disabled and verify balances first.
4. Use the smallest acceptable trade amount and exposure.
5. Enable trading during a supervised window.
6. Monitor logs, Binance orders, positions, fees, and dashboard state.
7. Keep the pilot running for several days before increasing exposure.

## 11. Health Checks and Monitoring

### Dashboard health

Add a lightweight endpoint or companion health check that confirms:

- The web process is alive.
- PostgreSQL is reachable.
- Schema version is current.

### Worker health

The worker should update a heartbeat at least every cycle. Alert when:

- Heartbeat is older than 2–3 expected cycles.
- Binance API authentication fails.
- Status writes fail repeatedly.
- An order result is uncertain.
- A position exists but cannot be priced.
- A stop-loss/TP sell fails.
- Exposure exceeds the configured limit.
- More than one worker attempts to acquire the lease.

Use external uptime monitoring for the dashboard and a scheduled heartbeat monitor for the worker. Do not rely only on the dashboard to report its own failure.

## 12. Persistence, Backup, and Retention

- Enable automated PostgreSQL backups appropriate to the selected Render plan.
- Export transaction history regularly to separate storage.
- Keep transactions and command audit records immutable.
- Retain detailed market history for a defined period, then aggregate or delete it.
- Test database restoration before production trading.
- Never restore production position state without reconciling it against the live Binance account.

## 13. Failure and Recovery Rules

### Worker restart

- Acquire the single-worker lease.
- Load tracked positions.
- Query Binance for relevant balances and uncertain orders.
- Reconcile state before placing any new order.
- Resume monitoring existing positions before scanning for new entries.

### Database outage

- Stop submitting new orders.
- Log a clear critical error.
- Do not continue trading from stale in-memory configuration.
- Alert the operator.

### Binance API outage or timeout

- Treat an order timeout as unknown, not failed.
- Query order status using the client order ID before retrying.
- Never blindly repeat a market order.

### Dashboard outage

- The worker may continue managing existing positions.
- Manual commands are unavailable.
- Automatic new entries should follow the last committed configuration.

Important: the current SL/TP implementation is bot-managed, not a native protective order held at Binance. If the worker or network is down, those exits are not guaranteed. A later hardening phase should evaluate exchange-native protective orders and their interaction with manual sells.

## 14. Rollback Plan

1. Set `ENABLE_TRADING=false` or activate the database hold flag.
2. Confirm no new entries can occur.
3. Keep monitoring existing positions or manage them directly in Binance.
4. Roll back the web service independently when possible.
5. Roll back the worker only after checking schema compatibility.
6. Reconcile all open positions and recent Binance orders after rollback.
7. Never restore an old database snapshot and immediately enable trading.

## 15. Acceptance Checklist

- [ ] Dashboard requires authentication.
- [ ] HTTPS works on the final domain.
- [ ] Binance secrets exist only on the worker.
- [ ] Withdrawals are disabled on the Binance API key.
- [ ] PostgreSQL is the shared source of truth.
- [ ] Exactly one worker can hold the trading lease.
- [ ] Worker heartbeat and stale alerts work.
- [ ] Trading defaults to disabled after initial deployment.
- [ ] Testnet automatic buy and every exit path pass.
- [ ] Manual commands show their final status in the dashboard.
- [ ] Duplicate command and restart tests pass.
- [ ] Exposure and maximum-position limits are enforced by the worker.
- [ ] Open positions survive worker and web restarts.
- [ ] Backups and restoration have been tested.
- [ ] Production pilot uses small amounts and active supervision.

## 16. Lower-Work Alternative (Not Preferred)

A single Render web service could run both Streamlit and the bot under a process supervisor and attach one persistent disk. This avoids the immediate PostgreSQL refactor, but it couples dashboard availability to trading, complicates crash handling, and provides weaker scaling and operational isolation.

Use this only for a temporary testnet deployment. Do not use a shell command that merely backgrounds `app.py`; use a supervisor that propagates shutdown signals, restarts failed child processes, and prevents duplicate workers.

## 17. Estimated Implementation Order

1. PostgreSQL schema and storage adapter.
2. Import utility for current JSON/JSONL data.
3. Database-backed worker lease and command queue.
4. Worker reconciliation and idempotent order handling.
5. Database-backed dashboard.
6. Authentication and audit log.
7. `render.yaml` and health checks.
8. Local integration tests.
9. Hosted analysis-only validation.
10. Testnet validation.
11. Restricted production pilot.

## 18. Official Render References

- Background workers: <https://render.com/docs/background-workers>
- Persistent disks: <https://render.com/docs/disks>
- PostgreSQL: <https://render.com/docs/postgresql-creating-connecting>
- Blueprints and `render.yaml`: <https://render.com/docs/blueprint-spec>
- Environment variables and secrets: <https://render.com/docs/configure-environment-variables>
- Health checks: <https://render.com/docs/health-checks>
- Streamlit deployment guide: <https://render.com/docs/deploy-streamlit>

Confirm current Render pricing, plan availability, disk limitations, outbound IP behavior, and database backup retention in the Render dashboard before production deployment.
