# RSU Ledger UK

A private, self-hosted Django application for UK employees who receive USD-denominated RSUs. It records grants, taxable vesting events, disposals and the GBP conversion evidence needed for a CGT working file.

## Stack

- Python 3.13, Django 5.2 and PostgreSQL
- `uv` for dependency locking and execution
- Django admin, session authentication and CSRF protection
- Optional generic OIDC login through django-allauth, using authorization code + PKCE
- Docker Compose for deployment

## Deploy

```sh
cp .env.example .env
# set strong POSTGRES_PASSWORD and DJANGO_SECRET_KEY, plus your external hostname
docker compose up -d --build
```

Create the first local administrator with `docker compose exec app uv run python manage.py createsuperuser`. Visit `/admin/` to create/manage users and inspect records. Back up the named `rsu-postgres` volume.

For OIDC, set `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`; then register this callback URL with the provider:

```text
https://your-rsu-host/accounts/oidc/company/login/callback/
```

The client should be confidential and use the authorization-code flow. The generic OpenID Connect integration uses PKCE and fetches the provider's userinfo claims.

## Optional Wise historical rates

Set `WISE_PERSONAL_API_TOKEN` to enable **Retrieve Wise rate**. The token is sent only as a
Bearer token to Wise and is never stored in the database or exposed in the browser. The app
retrieves the GBP-to-USD historical rate at noon UTC on the selected event date and stores the
timestamped source URL alongside the resulting rate.

## Optional Finnhub live stock prices

Set `FINNHUB_API_KEY` to retrieve current USD quotes for the non-blank tickers on Grants. The
Stock prices page refreshes a ticker only when its saved Finnhub quote is older than
`STOCK_PRICE_REFRESH_MINUTES` (15 by default). The token is sent only to Finnhub; it is not
stored in the database, included in source links, or exposed to the browser.

## SCIM provisioning

Set a long, independent `SCIM_BEARER_TOKEN` to enable the SCIM 2.0 endpoint at `/scim/v2/`. Provisioning clients must send `Authorization: Bearer <token>`; requests without the exact token receive `401`. Use a dedicated secret from your identity provider's provisioning configuration, not an end-user password or the Django secret key.

SCIM creates and updates Django users. Each newly created user receives a private ledger workspace, but SCIM provisioning **does not** grant access to another user's workspace. Manage any deliberate shared access through the app's owner access-management page.

## Roles and data separation

Every new user receives a separate private workspace. All grants, vests, sales and exchange-rate records are foreign-keyed to a workspace. Views derive the workspace only from the authenticated user’s membership, never from a browser-supplied workspace identifier.

- **Owner** — view/edit records and manage workspace membership.
- **Editor** — view/edit records.
- **Viewer** — view records only.
- **Django staff/superuser** — manage users and records via `/admin/`; becoming staff does not automatically join private workspaces.

An owner can grant or change access from **Manage access**. A user must sign in once before their email can be invited, preventing unverified automatic account creation.

## Local development

```sh
uv sync --group dev
export POSTGRES_HOST=localhost POSTGRES_PASSWORD=your-password
uv run python manage.py migrate
uv run python manage.py runserver
```

Run quality checks with `uv run ruff check .`, `uv run python manage.py check`, and `uv run pytest`.

## Tax scope

This is a record-keeping aid, not tax advice or a completed Self Assessment return. Retain employer/broker documents and the FX source for every event. The Overview dashboard's gain/loss and CGT figures are estimates only: it uses a chronological average-cost pool of net vested shares and does not apply same-day or 30-day share matching, losses brought forward, or the user's taxable-income position. Confirm the final calculation before filing.

Useful references:

- [HMRC HS305: employment-related securities](https://www.gov.uk/government/publications/employee-shares-and-securities-further-guidance-hs305-self-assessment-helpsheet/hs305-employment-related-shares-and-securities-further-guidance-2026)
- [HMRC CGT foreign currency guidance](https://www.gov.uk/hmrc-internal-manuals/capital-gains-manual/cg78310)
- [HMRC share identification guidance](https://www.gov.uk/hmrc-internal-manuals/capital-gains-manual/cg51550)
- [HMRC CGT rates and annual exempt amount](https://www.gov.uk/guidance/capital-gains-tax-rates-and-allowances)
