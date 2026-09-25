"""MIM-2038 — restore förfallodatum to its pre-upgrade value.

See migrations/19.0.1.0.12/pre-migration.py for why the backup exists: this
script is the half that guarantees no ärende's förfallodatum moved, whether or
not init_models() recomputed it while filling the new priority_days column.

Idempotent: the backup column is dropped once this has run, and the
column_exists guard above returns early when it is already gone — that is
what makes a second run a no-op. IS DISTINCT FROM only limits which rows the
first run's UPDATE touches; it does not by itself make a rerun safe, since a
second run would find the column already dropped before it ever reaches that
UPDATE.

If you are watching this upgrade's log: "restored due_date on 0 request(s)"
below is the expected outcome, not a sign the migration did not run. The
rehearsal for this release found that init_models() does not in fact dirty
due_date in this Odoo/Postgres combination, so the backup/restore pair here
is deliberate insurance rather than a fix for an observed problem. The lines
worth checking for a non-zero count are the pre-migration's "backed up" and
"remapped" ones instead.
"""

import logging

from odoo import api, SUPERUSER_ID
from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)

TABLE = "maintenance_request"
DUE_DATE_BACKUP = "_mim2038_due_date_backup"


def migrate(cr, version):
    if not column_exists(cr, TABLE, DUE_DATE_BACKUP):
        _logger.info("MIM-2038: no due_date backup column — nothing to restore.")
        return

    cr.execute(f"""
        UPDATE {TABLE}
        SET due_date = "{DUE_DATE_BACKUP}"
        WHERE due_date IS DISTINCT FROM "{DUE_DATE_BACKUP}"
    """)
    _logger.info("MIM-2038: restored due_date on %d request(s).", cr.rowcount)

    cr.execute(f'ALTER TABLE {TABLE} DROP COLUMN "{DUE_DATE_BACKUP}"')

    # Every statement above wrote via raw SQL, so anything already in cache
    # would keep serving pre-UPDATE values for the rest of this upgrade.
    api.Environment(cr, SUPERUSER_ID, {}).invalidate_all()
