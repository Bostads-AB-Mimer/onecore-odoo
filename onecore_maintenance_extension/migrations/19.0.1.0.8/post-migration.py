"""MIM-1954 — clean up lease_id values baked with a status-label suffix.

Before this fix, maintenance.lease.lease_id (Kontrakt ID — the identity
onecore_flag_sync_service.sync_lease_status sends to POST /leases/batch) was
populated from maintenance.lease.option.name, which is a DISPLAY string with
the Swedish status label appended, e.g. "705-023-04-0201/01 (Gällande)" (see
handlers/base_handler.py:_create_lease_option). Every lease created through
the manual search-and-select flow (record_management_service._save_lease)
before this fix therefore carries a lease_id the batch endpoint can never
match against OneCore's plain leaseId — kontraktsstatus-sync silently updates
nothing for those leases, forever: the cron only refreshes lease_status and
last_debit_date, it never repairs lease_id itself. The suffix pattern this
script strips (" (<label>)") has been baked into lease.name since the
"Adds contract status labels" commit, so on a production database this can
plausibly touch a large fraction of all leases ever created since then, not
just a handful — hence the single batched UPDATE below rather than a
per-record ORM loop, which would hold the upgrade transaction open far
longer on a large maintenance_lease table.

Leases created through the "empty rental object" auto-fill path
(record_management_service._create_lease) were never affected — that path
already wrote the raw API leaseId directly.

Idempotent: only rows whose lease_id ends in one of the five known status
labels are touched, so a re-run (or a database that never had the bug) finds
nothing to fix.
"""

import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.onecore_maintenance_extension.models.constants import (
    LEASE_STATUS_LABELS,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Plain Swedish words, no regex metacharacters — safe to inline directly
    # into the pattern without escaping.
    pattern = r" \((%s)\)$" % "|".join(LEASE_STATUS_LABELS.values())

    cr.execute(
        """
        UPDATE maintenance_lease
        SET lease_id = regexp_replace(lease_id, %s, '')
        WHERE lease_id ~ %s
        """,
        (pattern, pattern),
    )
    _logger.info(
        "MIM-1954: cleaned %d lease_id value(s) with a baked-in status suffix.",
        cr.rowcount,
    )

    # This runs after init_models() has already applied the current field
    # definitions (name is now computed from lease_id), so any maintenance.lease
    # loaded into cache earlier in this same upgrade transaction — by an
    # earlier module's migration, for instance — must be dropped, or it would
    # keep serving the pre-UPDATE lease_id/name for the rest of this process.
    api.Environment(cr, SUPERUSER_ID, {}).invalidate_all()
