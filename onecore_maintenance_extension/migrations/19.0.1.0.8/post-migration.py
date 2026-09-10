"""MIM-1954 — repair lease_id and name for leases already carrying a baked-in
status-label suffix.

Before this fix, maintenance.lease.lease_id (Kontrakt ID — the identity
onecore_flag_sync_service.sync_lease_status sends to POST /leases/batch) and
maintenance.lease.name (Kontrakt, shown on the ärende) were both populated
from maintenance.lease.option.name, which is a DISPLAY string with the
Swedish status label appended, e.g. "705-023-04-0201/01 (Gällande)" (see
handlers/base_handler.py:_create_lease_option). Every lease created through
the manual search-and-select flow (record_management_service._save_lease)
before this fix therefore had:

  - a lease_id the batch endpoint can never match against OneCore's plain
    leaseId, so kontraktsstatus-sync silently updated nothing for it, forever
    — the cron only refreshes lease_status and last_debit_date, it never
    repaired lease_id itself;
  - a name frozen at creation time that could disagree with its own
    lease_status once the cron *did* manage to refresh the latter (e.g.
    Kontrakt showing "(Kommande)" while Kontraktsstatus already said
    "Gällande") — name is now a stored compute
    (models/maintenance_lease.py:_compute_name, depends on lease_id and
    lease_status_label), so it recomputes automatically from now on and
    cannot drift again.

The suffix pattern both steps below deal with (" (<label>)") has been baked
into lease.name since the "Adds contract status labels" commit, months before
this release, so on a production database this can plausibly touch a large
fraction of all leases ever created since then, not just a handful — hence
two single batched UPDATEs rather than a per-record ORM loop, which would
hold the upgrade transaction open far longer on a large maintenance_lease
table and, for the name step, bump write_date on every row touched
(including already-correct ones), briefly misrepresenting "last modified"
across the entire lease history. The WHERE guards below keep each UPDATE to
only the rows that actually change.

Order matters within this script: lease_id must be repaired first, since the
name recompute (a SQL CASE expression mirroring _compute_name's own logic)
reads lease_id to build the corrected value. lease_status_label is a
brand-new column this same release adds, so init_models() has already
recomputed it fresh for every existing row by the time this post-migration
runs.

Leases created through the "empty rental object" auto-fill path
(record_management_service._create_lease) were never affected — that path
already wrote the raw API leaseId directly, so it never fed the suffix into
name.

Idempotent: both UPDATEs are guarded (a suffix match, and a
IS DISTINCT FROM comparison), so a re-run — or a database that never had the
bug — finds nothing left to fix.
"""

import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.onecore_maintenance_extension.models.constants import (
    LEASE_STATUS_LABELS,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _fix_lease_id(cr)
    _recompute_name(cr)

    # Both steps write via raw SQL, so any maintenance.lease already loaded
    # into cache earlier in this same upgrade transaction — by an earlier
    # module's migration, for instance — must be dropped, or it would keep
    # serving pre-UPDATE values for the rest of this process.
    api.Environment(cr, SUPERUSER_ID, {}).invalidate_all()


def _fix_lease_id(cr):
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


def _recompute_name(cr):
    # lease_status is a brand-new Integer column with no SQL default, so
    # every pre-existing row has it NULL rather than 0 — but the ORM (both
    # _compute_lease_status_label and this same migration's init_models()
    # pass) reads a NULL Integer as 0 ("Gällande"). COALESCE here mirrors
    # that so the CASE below doesn't fall through to the bare-lease_id ELSE
    # branch for exactly the pre-existing rows the ORM already treats as
    # status 0.
    when_clauses = "\n            ".join(
        f"WHEN COALESCE(lease_status, 0) = {status} THEN lease_id || ' ({label})'"
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
