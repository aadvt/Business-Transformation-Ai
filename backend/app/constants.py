"""Single-tenant constant. This is a one-organisation hackathon demo — every
seeded row belongs to this org, and every audit-log write from a router needs
an org_id to scope its (or its disruption's) hash chain. Shared here so
app/seed.py and app/repositories/* agree on the same id without importing
the seed script itself.
"""

DEFAULT_ORG_ID = "b2f6c8a0-0000-4000-8000-000000000001"
