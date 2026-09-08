"""MIM-1954 — recompute maintenance.lease.name for every existing lease.

Before this fix, maintenance.lease.name was a plain Char baked once at
creation as "<leaseId> (<status label>)" and never touched again.
sync_lease_status refreshes lease_status (and, via _compute_lease_status_label,
lease_status_label) hourly, but had no way to also refresh a plain string
field — so a lease's displayed "Kontrakt" could keep showing a stale status
suffix (e.g. "(Kommande)") right next to a freshly-updated Kontraktsstatus
("Gällande") on the very same ärende.

name is now a stored compute (models/maintenance_lease.py:_compute_name,
depends on lease_id and lease_status_label), so going forward it recomputes
automatically every time the cron changes lease_status and can never drift
again. But retrofitting an *existing* column onto a compute does not
retroactively recompute already-persisted rows — init_models() only
auto-recomputes a field the first time its column is created, and the name
column has existed since long before this release — so this migration forces
that recompute once, for every lease already in the database.

Must run after 19.0.1.0.8/post-migration.py (same upgrade, later version):
that script is what makes lease_id trustworthy on rows that used to carry the
same baked-in status suffix, and lease_status_label is a brand-new column
this same release adds, so init_models() has already recomputed it fresh for
every existing row by the time this script runs.

A single batched UPDATE, not a per-record ORM loop calling _compute_name():
this table plausibly holds one row per maintenance case ever created with a
lease, so an ORM loop would open the upgrade transaction for far longer than
necessary and — worse — bump write_date on every single row, including ones
whose name was already correct, which would make "last modified" sorting and
any write_date-based reporting briefly show the entire lease history as just
touched. The WHERE guard below (name IS DISTINCT FROM the recomputed value)
keeps this to only the rows that actually change, mirroring _compute_name's
own logic (lease_id + LEASE_STATUS_LABELS) as a SQL CASE expression — kept
here as a deliberate, one-time duplication rather than a shared helper, per
this repo's migration convention of self-contained scripts (see
19.0.1.0.6/post-migration.py's GREATEST/COALESCE precedent).

Idempotent: a second run's WHERE guard matches nothing once every name
already agrees with its own lease_id/lease_status.
"""

import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.onecore_maintenance_extension.models.constants import (
    LEASE_STATUS_LABELS,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    when_clauses = "\n            ".join(
        f"WHEN lease_status = {status} THEN lease_id || ' ({label})'"
        for status, label in LEASE_STATUS_LABELS.items()
    )

    cr.execute(f"""
        UPDATE maintenance_lease AS ml
        SET name = computed.new_name
        FROM (
            SELECT id,
                CASE
                    WHEN lease_id IS NULL THEN NULL
                    {when_clauses}
                    ELSE lease_id
                END AS new_name
            FROM maintenance_lease
        ) AS computed
        WHERE ml.id = computed.id
          AND ml.name IS DISTINCT FROM computed.new_name
    """)
    _logger.info("MIM-1954: recomputed name on %d lease(s).", cr.rowcount)

    # name is computed now (init_models() already applied that definition by
    # the time this post-migration runs), so any maintenance.lease cached
    # earlier in this same upgrade transaction must be dropped, or it would
    # keep serving the pre-UPDATE name for the rest of this process.
    api.Environment(cr, SUPERUSER_ID, {}).invalidate_all()
