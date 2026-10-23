"""MIM-1954 — recover lease_status, and repair lease_id and name, for leases
already carrying a baked-in status-label suffix.

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

That same _save_lease also dropped the option's lease_status on the floor
rather than persisting it, and maintenance.lease.lease_status is a brand-new
column this release adds with no SQL default — so on every pre-existing row
it is NULL, and **the suffix is the only surviving record of what the
contract's status was**. Recovering it (_recover_lease_status below) has to
happen before _fix_lease_id strips that suffix away, or the information is
gone: the ORM reads a NULL Integer as 0, so every legacy lease — including
ones that plainly said "(Uppsagt)" or "(Upphört)" — would come out of this
migration relabelled "Gällande". The cron would eventually correct the open
ones (after posting a false "Gällande → Uppsagt" note on each), and closed
ärenden, which open_requests() excludes, would keep the wrong label forever.

Leases created through the "empty rental object" auto-fill path
(record_management_service._create_lease) were never affected by the
lease_id/name corruption — that path already wrote the raw API leaseId
directly, so it never fed the suffix into either field. It never recorded a
status either, though, and with no suffix to read there is nothing to recover
from; those rows get UNKNOWN_LEASE_STATUS ("Okänd status") rather than a
fabricated "Gällande". The cron corrects the open ones on its next run.

The suffix pattern the first two steps deal with (" (<label>)") has been baked
into lease.name since the "Adds contract status labels" commit, months before
this release, so on a production database this can plausibly touch a large
fraction of all leases ever created since then, not just a handful — hence
batched UPDATEs rather than a per-record ORM loop, which would hold the
upgrade transaction open far longer on a large maintenance_lease table and,
for the name step, bump write_date on every row touched (including
already-correct ones), briefly misrepresenting "last modified" across the
entire lease history. The WHERE guards below keep each UPDATE to only the
rows that actually change.

Order matters within this script, and all four steps are load-bearing:

  1. _recover_lease_status — read the status back out of the suffix, while
     the suffix still exists.
  2. _fix_lease_id — strip the suffix. Must follow (1), and must precede (4),
     since the name recompute reads lease_id to build the corrected value.
  3. _recompute_lease_status_label — lease_status_label is a stored compute on
     a brand-new column, so init_models() has already filled it in for every
     existing row by the time this post-migration runs — from the NULL
     lease_status of step (1)'s input, i.e. "Gällande" across the board. Raw
     SQL on lease_status does not retrigger that compute, so the label has to
     be rewritten here by hand.
  4. _recompute_name — a SQL CASE expression mirroring _compute_name's own
     logic, over the now-correct lease_id and lease_status.

Idempotent: every UPDATE is guarded (a suffix match, a NULL-status match, or
an IS DISTINCT FROM comparison), so a re-run — or a database that never had
the bug — finds nothing left to fix.
"""

import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.onecore_maintenance_extension.models.constants import (
    LEASE_STATUS_LABELS,
)
from odoo.addons.onecore_maintenance_extension.models.utils.helpers import (
    UNKNOWN_LEASE_STATUS,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _recover_lease_status(cr)
    _fix_lease_id(cr)
    _recompute_lease_status_label(cr)
    _recompute_name(cr)

    # Every step writes via raw SQL, so any maintenance.lease already loaded
    # into cache earlier in this same upgrade transaction — by an earlier
    # module's migration, for instance — must be dropped, or it would keep
    # serving pre-UPDATE values for the rest of this process.
    api.Environment(cr, SUPERUSER_ID, {}).invalidate_all()


def _suffix_pattern(label):
    # Plain Swedish words, no regex metacharacters — safe to inline directly
    # into the pattern without escaping.
    return r" \(%s\)$" % label


def _any_suffix_pattern():
    return r" \((%s)\)$" % "|".join(LEASE_STATUS_LABELS.values())


def _recover_lease_status(cr):
    """Read each legacy row's creation-time status back out of its suffix.

    Only rows whose lease_status is still NULL are touched, so a status the
    cron (or a post-fix creation) has already written is never overwritten.
    The suffix is looked for on lease_id, falling back to name for a row
    whose lease_id was never corrupted but whose name carries one anyway.
    """
    when_clauses = "\n                ".join(
        f"WHEN src ~ '{_suffix_pattern(label)}' THEN {status}"
        for status, label in LEASE_STATUS_LABELS.items()
    )

    cr.execute(f"""
        UPDATE maintenance_lease AS ml
        SET lease_status = recovered.status
        FROM (
            SELECT id,
                CASE
                    {when_clauses}
                    ELSE {UNKNOWN_LEASE_STATUS}
                END AS status
            FROM (
                SELECT id,
                    CASE
                        WHEN lease_id ~ '{_any_suffix_pattern()}' THEN lease_id
                        ELSE name
                    END AS src
                FROM maintenance_lease
                WHERE lease_status IS NULL
            ) AS s
        ) AS recovered
        WHERE ml.id = recovered.id
          AND ml.lease_status IS NULL
    """)
    _logger.info(
        "MIM-1954: recovered lease_status on %d lease(s) with no stored status.",
        cr.rowcount,
    )


def _fix_lease_id(cr):
    pattern = _any_suffix_pattern()

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


def _recompute_lease_status_label(cr):
    # Mirrors _compute_lease_status_label: an unmapped code has no label, and
    # a NULL lease_status reads as 0 ("Gällande") through the ORM. After
    # _recover_lease_status there should be no NULL left, but the COALESCE
    # keeps this step's answer identical to the ORM's for any row a later
    # concurrent insert leaves behind.
    when_clauses = "\n                ".join(
        f"WHEN COALESCE(lease_status, 0) = {status} THEN '{label}'"
        for status, label in LEASE_STATUS_LABELS.items()
    )

    cr.execute(f"""
        UPDATE maintenance_lease AS ml
        SET lease_status_label = computed.new_label
        FROM (
            SELECT id,
                CASE
                    {when_clauses}
                    ELSE NULL
                END AS new_label
            FROM maintenance_lease
        ) AS computed
        WHERE ml.id = computed.id
          AND ml.lease_status_label IS DISTINCT FROM computed.new_label
    """)
    _logger.info("MIM-1954: recomputed lease_status_label on %d lease(s).", cr.rowcount)


def _recompute_name(cr):
    when_clauses = "\n                ".join(
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
