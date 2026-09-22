"""MIM-2038 — remap the retired priority values onto the custom-weeks escape.

priority_expanded used to carry the day count in its own Selection value
("14" = 2 veckor, "183" = 6 månader). MIM-2038 keeps only the short presets
and replaces the long tail with PRIORITY_CUSTOM plus a priority_weeks integer,
so every row still sitting on a retired value has to be remapped BEFORE
init_models() validates the column against the new, shorter selection list.

Odoo runs every applicable pre-migration, THEN init_models() (which creates
any column the current field definitions declare and fills newly-added stored
computes for every existing row), THEN every post-migration — the ordering
documented in migrations/19.0.1.0.7/pre-migration.py. Two consequences shape
this script:

  - priority_weeks does not exist yet. init_models() has not run, so the
    column has to be created here by hand or step 3 has nowhere to write.
  - priority_days and priority_label are brand-new stored computes.
    init_models() will fill them for every row from whatever this script
    leaves in priority_expanded and priority_weeks, so getting those two
    right here is all that is needed — exactly the mechanism
    migrations/19.0.1.0.10/post-migration.py describes for
    lease_status_label.

The due_date backup is defensive. Raw SQL does not retrigger an existing
stored compute, so the priority_expanded rewrite alone would leave due_date
alone — but due_date @api.depends on priority_days, which init_models() fills
through the ORM, and that fill may well mark due_date dirty. Whether it
actually does has not been established, and the two outcomes differ on real
data: 183 -> 26 veckor is 182 days, so a recompute would move a live ärende's
förfallodatum by a day, and any ärende with a hand-typed due_date (which
_inverse_due_date exists to protect) would be overwritten. Backing the column
up here and restoring it in post-migration makes the outcome the same either
way: no ärende's förfallodatum changes.

Idempotent: the UPDATE is guarded on the retired values, which no longer
exist after a successful run, and both ADD COLUMNs use IF NOT EXISTS.
"""

import logging

from odoo.addons.onecore_maintenance_extension.models.constants import (
    LEGACY_PRIORITY_WEEKS,
    PRIORITY_CUSTOM,
)

_logger = logging.getLogger(__name__)

TABLE = "maintenance_request"
DUE_DATE_BACKUP = "_mim2038_due_date_backup"


def migrate(cr, version):
    _add_columns(cr)
    _backup_due_date(cr)
    _remap_retired_values(cr)


def _add_columns(cr):
    cr.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS priority_weeks integer")
    cr.execute(f'ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS "{DUE_DATE_BACKUP}" date')


def _backup_due_date(cr):
    cr.execute(f'UPDATE {TABLE} SET "{DUE_DATE_BACKUP}" = due_date')
    _logger.info("MIM-2038: backed up due_date on %d request(s).", cr.rowcount)


def _remap_retired_values(cr):
    """Retired value -> PRIORITY_CUSTOM + the equivalent number of weeks."""
    when_clauses = "\n            ".join(
        f"WHEN '{value}' THEN {weeks}" for value, weeks in LEGACY_PRIORITY_WEEKS.items()
    )
    values = tuple(LEGACY_PRIORITY_WEEKS)

    cr.execute(
        f"""
        UPDATE {TABLE}
        SET priority_weeks = CASE priority_expanded
            {when_clauses}
            END,
            priority_expanded = %s
        WHERE priority_expanded IN %s
        """,
        (PRIORITY_CUSTOM, values),
    )
    _logger.info(
        "MIM-2038: remapped %d request(s) from a retired priority value.", cr.rowcount
    )
