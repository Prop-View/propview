# Tenant Data Retention

`retention_scan.py` is a one-shot job that enumerates active tenants through
the restricted platform registry function and applies each tenant's
`tenant_data_retention.retention_days` policy inside `tenant_connection()`.
It clears old interaction transcript text and deletes old structured
conversation turns and tool invocations. Call analytics and consent records
are retained.

Apply database migrations through `015_data_governance.sql`, then configure a
positive retention period for each tenant through the Admin API:

```http
PUT /admin/tenants/{tenant_id}/privacy/retention
Authorization: Bearer <tenant API key>
Content-Type: application/json

{"retention_days": 365}
```

Run the one-shot scan from a scheduler or manually:

```bash
cd services/data-retention
DATABASE_URL=postgresql://propview_app:<password>@<host>/<database> \
  python retention_scan.py
```

No retention interval is invented as a global default: a tenant without an
explicit policy causes the job to fail for that run rather than deleting data
under an undocumented assumption. The registry function enumerates active
tenants without granting the application role broad access to platform tables.
