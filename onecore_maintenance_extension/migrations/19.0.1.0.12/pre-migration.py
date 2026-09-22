"""MIM-2038 — remap the retired priority values onto the custom-weeks escape.

priority_expanded used to carry the day count in its own Selection value
("14" = 2 veckor, "183" = 6 månader). MIM-2038 keeps only the short presets
and replaces the long tail with PRIORITY_CUSTOM plus a priority_weeks integer,
so every row still sitting on a retired value has to be remapped BEFORE
init_models() fills the new priority_days/priority_label stored computes from
whatever priority_expanded/priority_weeks contain at that point.

This is NOT because Odoo would otherwise reject a stored value that fell out
of the Python-declared Selection — it doesn't, and an earlier draft of this
docstring claimed it did. Removing "183" from PRIORITY_PRESETS makes
ir.model.fields.selection._update_selection() (odoo/addons/base/models/
ir_model.py) delete the matching selection row and log a "Removing selection
value" warning, which unlinks through _process_ondelete(); but that method
only takes action on a value's removal when the field declares an `ondelete`
policy for it, or the field is `manual`, and priority_expanded is neither (no
`ondelete=` kwarg, not a manual/custom field) — so it hits `continue` and does
nothing to the maintenance_request table. A row can sit on "183" forever
without Odoo ever objecting to it at the schema or ORM level. Verified against
this repo's odoo/ checkout (branch 19.0) before writing this paragraph.

What actually breaks if this script does not remap the row first is the
compute fill described next.

Odoo runs every applicable pre-migration, THEN init_models() (which creates
any column the current field definitions declare and fills newly-added stored
computes for every existing row), THEN every post-migration — the ordering
documented in migrations/19.0.1.0.7/pre-migration.py. Two consequences shape
this script:

  - priority_weeks does not exist yet. init_models() has not run, so the
    column has to be created here by hand or step 3 has nowhere to write.
  - priority_days and priority_label are brand-new stored computes.
    init_models() will fill them for every row from whatever this script
    leaves in priority_expanded and priority_weeks. An unremapped "183"
    would compute priority_days = int("183") = 183 and, since 183 % 7 != 0,
    priority_label = "183 dagar" — instead of the correct
    priority_days = 182 / priority_label = "26 veckor". Getting
    priority_expanded and priority_weeks right here, before that fill runs,
    is all that is needed — exactly the mechanism
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

The backup only ever captures once. _backup_due_date checks whether
DUE_DATE_BACKUP already existed BEFORE _add_columns creates it (the check has
to happen first — after ADD COLUMN IF NOT EXISTS the column always exists, so
a post-hoc check could never tell "already there" from "just created"). A
retry that finds an existing backup — e.g. this pre-migration committed but
the matching post-migration never ran, so the backup column is still sitting
there — leaves it alone instead of overwriting a possibly-still-good backup
with whatever due_date holds right now, which could already be a bad
recompute.

Idempotent: the remap UPDATE is guarded on the retired values, which no
longer exist after a successful run; both ADD COLUMNs use IF NOT EXISTS; and
the due_date backup only fires when DUE_DATE_BACKUP did not already exist, as
described above.
"""

import logging

from odoo.tools.sql import column_exists

from odoo.addons.onecore_maintenance_extension.models.constants import (
    LEGACY_PRIORITY_WEEKS,
    PRIORITY_CUSTOM,
)

_logger = logging.getLogger(__name__)

TABLE = "maintenance_request"
DUE_DATE_BACKUP = "_mim2038_due_date_backup"


def migrate(cr, version):
    # Captured BEFORE _add_columns runs: once ADD COLUMN IF NOT EXISTS has
    # executed the column always exists, so this is the only point at which
    # "already there" and "just created" are still distinguishable.
    backup_already_present = column_exists(cr, TABLE, DUE_DATE_BACKUP)
    _add_columns(cr)
    _backup_due_date(cr, skip=backup_already_present)
    _remap_retired_values(cr)


def _add_columns(cr):
    cr.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS priority_weeks integer")
    cr.execute(f'ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS "{DUE_DATE_BACKUP}" date')


def _backup_due_date(cr, skip):
    """Capture due_date into DUE_DATE_BACKUP, unless a backup is already there.

    skip=True means DUE_DATE_BACKUP existed before this migrate() call, i.e.
    a previous run of this pre-migration committed but its matching
    post-migration never ran (or hasn't yet). Overwriting that backup here
    would blow away the one copy of due_date from before anything touched
    it, with whatever due_date holds right now — which, per the module
    docstring, might already be a bad recompute. So a pre-existing backup is
    left untouched instead.
    """
    if skip:
        _logger.info(
            "MIM-2038: %s already existed — leaving the existing due_date backup alone.",
            DUE_DATE_BACKUP,
        )
        return
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
