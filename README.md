# RSU Ledger UK

A small, local-first ledger for a UK taxpayer receiving USD-denominated RSUs. It records grants, vesting and sales, converts each event to GBP using the rate you enter, and provides a transparent share-matching CGT estimate.

## Deployment (Docker Compose)

This release persists data in PostgreSQL and is intended to be run behind an HTTPS reverse proxy.

```sh
cp .env.example .env
# edit secrets, APP_URL and (optionally) OIDC settings
docker compose up -d --build
```

Visit `APP_URL`, then use **Create first administrator** once. The bootstrap endpoint closes as soon as the first user is created. Back up the named `rsu-postgres` Docker volume as part of your normal backup regime.

`AUTH_MODE=local` provides password sign-in. `AUTH_MODE=oidc` requires an OIDC provider; `hybrid` enables both. Register the redirect URI as:

```text
https://your-rsu-host/auth/oidc/callback
```

The OIDC client must be confidential and use the Authorization Code flow. Set `APP_URL` to the external HTTPS URL so the callback and secure session cookie are correct.

## Users, permissions and data isolation

Each user receives their own private workspace and ledger when first created or authenticated. Ledger reads and writes require an explicit workspace-membership check in the API; a user cannot retrieve another workspace by guessing its ID.

- **Owner** — can read/write the workspace and grant/revoke member access.
- **Editor** — can read/write the workspace.
- **Viewer** — can read only.
- **System administrator** — can create local users through `POST /api/users`; this does not grant access to their private workspaces.

Workspace membership routes are available at `/api/workspaces/:workspaceId/members` to workspace owners. A user must authenticate at least once before an owner can invite their email address. This deliberate constraint prevents an invite from silently creating an unverified account.

The browser client saves changes through the authenticated API; it no longer treats browser local storage as the authoritative copy. The server stores a ledger document per workspace in PostgreSQL and session cookies are `HttpOnly`, `SameSite=Lax` and marked `Secure` in production.

## Run locally without Docker

```sh
npm install
npm run db:migrate
npm run dev
```

Set `DATABASE_URL`, `SESSION_SECRET` and `APP_URL` first (see `.env.example`). Start the deployable server with `npm run build && npm start`.

**Export CSV** regularly. Your ledger is persisted to the configured PostgreSQL database; no third-party application receives the ledger data.

## Exchange rates

Every vest and sale keeps its own GBP-per-USD rate: both the acquisition/taxable amount and disposal proceeds are converted into sterling at their respective dates. The **HMRC rate sources** button stores published [spot](https://www.trade-tariff.service.gov.uk/exchange_rates/spot), [monthly](https://www.trade-tariff.service.gov.uk/exchange_rates/monthly), or [average](https://www.trade-tariff.service.gov.uk/exchange_rates/average) rates (entered as HMRC's `USD per GBP` quote) and links the selected type, period and source URL to a transaction. You can still enter a spot or broker rate directly.

HMRC does not prescribe a single CGT exchange-rate reference point; use a reasonable, consistent method and retain the evidence. HMRC's average-rate publications cover rolling 12-month periods ending 31 March and 31 December; their monthly-rate service is intended for customs valuation. Do not use a later rate to convert a final USD gain—all costs and proceeds are converted separately on their relevant dates.

## Important scope

This is a record-keeping aid, not tax advice or a completed Self Assessment return. It does not calculate Income Tax/NIC, nor the final CGT liability, annual exempt amount or tax rate. Enter the employer-confirmed taxable vest value and deductions, and retain the original payslip, broker statements, grant documents and FX evidence.

The disposal view approximates the UK identification order for ordinary listed shares: same-day acquisitions, acquisitions in the following 30 days, then the Section 104 pool. It requires the complete history of acquisitions for the particular share class to be reliable. Overseas duties, restricted/non-listed securities, share elections and corporate actions need specialist review.

## References

- [HMRC HS305 Employment-related shares and securities (2026)](https://www.gov.uk/government/publications/employee-shares-and-securities-further-guidance-hs305-self-assessment-helpsheet/hs305-employment-related-shares-and-securities-further-guidance-2026)
- [HMRC Capital Gains manual: share identification](https://www.gov.uk/hmrc-internal-manuals/capital-gains-manual/cg51550)
- [HMRC Capital Gains manual: foreign currency assets](https://www.gov.uk/hmrc-internal-manuals/capital-gains-manual/cg78310)
- [HMRC average exchange rates](https://www.trade-tariff.service.gov.uk/exchange_rates/average)
- [HMRC employee share scheme overview](https://www.gov.uk/tax-employee-share-schemes)
- [RPP: Restricted Securities / RSUs](https://rppaccounts.co.uk/restricted-share-units/)
- [Frazer James: RSUs guide](https://frazerjames.co.uk/rsus-a-tech-employees-guide-2/)
