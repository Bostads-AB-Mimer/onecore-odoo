"""MIM-1954 — clean up lease_id values baked with a status-label suffix.

Before this fix, maintenance.lease.lease_id (Kontrakt — the identity
onecore_flag_sync_service.sync_lease_status sends to POST /leases/batch) was
populated from maintenance.lease.option.name, which is a DISPLAY string with
the Swedish status label appended, e.g. "705-023-04-0201/01 (Gällande)" (see
handlers/base_handler.py:_create_lease_option). Every lease created through
the manual search-and-select flow (record_management_service._save_lease)
before this fix therefore carries a lease_id the batch endpoint can never
match against OneCore's plain leaseId — kontraktsstatus-sync silently updates
nothing for those leases, forever: the cron only refreshes lease_status and
last_debit_date, it never repairs lease_id itself.

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
    env = api.Environment(cr, SUPERUSER_ID, {})

    suffixes = tuple(f" ({label})" for label in LEASE_STATUS_LABELS.values())
    leases = env["maintenance.lease"].search([("lease_id", "!=", False)])

    fixed = 0
    for lease in leases:
        for suffix in suffixes:
            if lease.lease_id.endswith(suffix):
                lease.lease_id = lease.lease_id[: -len(suffix)]
                fixed += 1
                break

    _logger.info(
        "MIM-1954: cleaned %d of %d candidate lease_id value(s) with a baked-in status suffix.",
        fixed,
        len(leases),
    )
