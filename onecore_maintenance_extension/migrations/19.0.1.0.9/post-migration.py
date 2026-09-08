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
every existing row by the time this script runs (see module docstring
precedent in 19.0.1.0.8/post-migration.py). Calling _compute_name() here
reuses the exact single-source-of-truth logic instead of duplicating it.

Idempotent: recomputing an already-correct name is a no-op write.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    leases = env["maintenance.lease"].search([])
    leases._compute_name()
    env.flush_all()
    _logger.info("MIM-1954: recomputed name on %d lease(s).", len(leases))
