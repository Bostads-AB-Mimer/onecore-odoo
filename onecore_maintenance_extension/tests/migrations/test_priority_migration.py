"""Tests for migrations/19.0.1.0.12/{pre,post}-migration.py (MIM-2038).

Final whole-branch review, item 2: zero lines of the 19.0.1.0.12 migration
were executed by any test before this file existed. The migration itself was
verified once, by hand, on a rehearsal copy (see the docstring on
post-migration.py) — what was missing was regression protection for a future
edit to either script.

Two things this migration must keep true, both exercised below:

1. Every retired priority_expanded value (14/21/28/35/42/56/183/365 days)
   remaps to PRIORITY_CUSTOM with the matching priority_weeks, and a value
   that is still valid today (a short preset, or no priority at all) is left
   alone. 21/28/35 were never touched by the pre-release rehearsal — this is
   what closes that gap.
2. due_date backed up in pre-migration comes back out unchanged in
   post-migration, regardless of what happens to due_date in between. This is
   the ordering regression the final review flagged: _remap_retired_values
   runs AFTER _backup_due_date in migrate() specifically so the backup
   captures pre-remap values. Swap that order and the backup would capture
   post-remap due_dates instead — on a build where something in between does
   dirty due_date, the restore would then "restore" the wrong date. These
   tests call the real migrate() functions in the real order, so a future
   reordering of those two calls would show up here as a failing round trip.
"""

import importlib.util
import os
from datetime import timedelta

from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.tools.sql import column_exists

from ...models.constants import LEGACY_PRIORITY_WEEKS, PRIORITY_CUSTOM
from ..utils.test_utils import create_maintenance_request

TABLE = "maintenance_request"
DUE_DATE_BACKUP = "_mim2038_due_date_backup"


def _load_migration(filename, module_name):
    """Load a migrations/19.0.1.0.12/*.py script by file path.

    Migration directories (``19.0.1.0.12``) are not valid Python package
    names, so they cannot be imported normally — same idiom already used by
    tests/models/services/test_lease_suffix_migration.py for the
    19.0.1.0.10 post-migration.
    """
    module_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    path = os.path.join(module_root, "migrations", "19.0.1.0.12", filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("onecore")
class TestPriorityMigrationRemap(TransactionCase):
    """Coverage for pre-migration.py's _remap_retired_values."""

    def setUp(self):
        super().setUp()
        self.pre_migration = _load_migration(
            "pre-migration.py", "mim_2038_pre_migration"
        )

    def _force_priority_expanded(self, value):
        """Write a priority_expanded value the ORM would reject.

        The eight retired values are no longer valid Selection entries, so
        create()/write() refuse them outright — raw SQL is the only honest
        way to reproduce what a genuinely pre-migration row looks like on
        disk, exactly as a real pre-19.0.1.0.12 database would have it.
        """
        request = create_maintenance_request(self.env, priority_expanded="0")
        # Stored computes (priority_days, due_date, ...) are only written to
        # their DB columns on flush — without this, the raw UPDATE below
        # would edit a row whose real columns are still unset, and a later
        # ORM read would recompute over it and mask whatever the UPDATE did.
        self.env.flush_all()
        self.env.cr.execute(
            f"UPDATE {TABLE} SET priority_expanded = %s WHERE id = %s",
            (value, request.id),
        )
        return request

    def _read_priority(self, request_id):
        self.env.cr.execute(
            f"SELECT priority_expanded, priority_weeks FROM {TABLE} WHERE id = %s",
            (request_id,),
        )
        return self.env.cr.fetchone()

    def test_remaps_each_retired_value_to_custom_with_matching_weeks(self):
        """Every entry in LEGACY_PRIORITY_WEEKS, not just the ones the
        pre-release rehearsal happened to touch (14, 42, 56, 183, 365) — this
        closes the gap that 21, 28 and 35 were never exercised."""
        requests = {
            value: self._force_priority_expanded(value)
            for value in LEGACY_PRIORITY_WEEKS
        }
        self.env.invalidate_all()

        self.pre_migration._remap_retired_values(self.env.cr)

        for value, weeks in LEGACY_PRIORITY_WEEKS.items():
            priority_expanded, priority_weeks = self._read_priority(requests[value].id)
            self.assertEqual(
                priority_expanded, PRIORITY_CUSTOM, "retired value %s" % value
            )
            self.assertEqual(priority_weeks, weeks, "retired value %s" % value)

    def test_leaves_a_still_valid_preset_untouched(self):
        """A still-valid preset must not be touched by the remap — including
        one that (like every real migrated row, per final-review item 1)
        already carries a leftover priority_weeks from a past 'custom'."""
        for preset in ("0", "7"):
            request = create_maintenance_request(
                self.env, priority_expanded=preset, priority_weeks=9
            )
            self.env.flush_all()

            self.pre_migration._remap_retired_values(self.env.cr)

            priority_expanded, priority_weeks = self._read_priority(request.id)
            self.assertEqual(priority_expanded, preset)
            self.assertEqual(priority_weeks, 9)

    def test_leaves_a_null_priority_untouched(self):
        request = create_maintenance_request(self.env, priority_expanded=False)
        self.env.flush_all()

        self.pre_migration._remap_retired_values(self.env.cr)

        priority_expanded, _priority_weeks = self._read_priority(request.id)
        self.assertIsNone(priority_expanded)


@tagged("onecore")
class TestPriorityMigrationDueDateBackup(TransactionCase):
    """Coverage for the pre/post-migration due_date backup-and-restore pair.

    This is the ordering regression from the final review: the backup must
    capture due_date BEFORE the remap runs, so it always holds the original,
    pre-upgrade value no matter what happens to due_date afterwards.
    """

    def setUp(self):
        super().setUp()
        self.pre_migration = _load_migration(
            "pre-migration.py", "mim_2038_pre_migration"
        )
        self.post_migration = _load_migration(
            "post-migration.py", "mim_2038_post_migration"
        )

    def test_backup_and_restore_round_trip_preserves_due_date(self):
        request = create_maintenance_request(self.env, priority_expanded="7")
        original_due_date = request.due_date
        # due_date is a stored compute; it only reaches its DB column on
        # flush. Without this, pre_migration's backup UPDATE would run
        # against a row whose due_date column is still unset, and any later
        # ORM read would silently recompute over whatever raw SQL wrote.
        self.env.flush_all()

        # The real migrate() — same call, same internal ordering (backup,
        # then remap) as production. If that ordering is ever swapped this
        # test starts failing rather than the round trip silently going
        # stale.
        self.pre_migration.migrate(self.env.cr, "19.0.1.0.12")

        # Perturb due_date directly, simulating whatever init_models() might
        # do to a stored compute that depends on priority_days once the new
        # columns exist — the exact uncertainty the backup exists to cover.
        perturbed = original_due_date + timedelta(days=99)
        self.env.cr.execute(
            f"UPDATE {TABLE} SET due_date = %s WHERE id = %s",
            (perturbed, request.id),
        )
        self.env.invalidate_all()
        self.assertEqual(request.due_date, perturbed)

        self.post_migration.migrate(self.env.cr, "19.0.1.0.12")
        self.env.invalidate_all()

        self.assertEqual(request.due_date, original_due_date)

    def test_post_migration_drops_the_backup_column_so_a_rerun_is_a_no_op(self):
        request = create_maintenance_request(self.env, priority_expanded="7")
        self.env.flush_all()

        self.pre_migration.migrate(self.env.cr, "19.0.1.0.12")
        self.assertTrue(column_exists(self.env.cr, TABLE, DUE_DATE_BACKUP))

        self.post_migration.migrate(self.env.cr, "19.0.1.0.12")
        self.assertFalse(column_exists(self.env.cr, TABLE, DUE_DATE_BACKUP))

        # A second run must find the column already gone and do nothing,
        # not error out trying to read/drop a column that no longer exists.
        due_date_before_rerun = request.due_date
        self.post_migration.migrate(self.env.cr, "19.0.1.0.12")
        request.invalidate_recordset()
        self.assertEqual(request.due_date, due_date_before_rerun)

    def test_a_preexisting_backup_is_not_overwritten_by_a_second_pre_migration_run(
        self,
    ):
        """Mirrors _backup_due_date's own docstring scenario: the
        pre-migration committed once already (backup column present) but the
        matching post-migration never ran. A second pre-migration run must
        leave that existing backup alone rather than overwrite it with
        due_date's current — possibly already wrong — value."""
        request = create_maintenance_request(self.env, priority_expanded="7")
        self.env.flush_all()

        self.pre_migration.migrate(self.env.cr, "19.0.1.0.12")
        self.env.cr.execute(
            f'SELECT "{DUE_DATE_BACKUP}" FROM {TABLE} WHERE id = %s',
            (request.id,),
        )
        (first_backup,) = self.env.cr.fetchone()

        # due_date changes after the backup was taken, e.g. a hand-typed
        # override written between the two migration runs.
        self.env.cr.execute(
            f"UPDATE {TABLE} SET due_date = %s WHERE id = %s",
            (first_backup + timedelta(days=30), request.id),
        )

        self.pre_migration.migrate(self.env.cr, "19.0.1.0.12")

        self.env.cr.execute(
            f'SELECT "{DUE_DATE_BACKUP}" FROM {TABLE} WHERE id = %s',
            (request.id,),
        )
        (second_backup,) = self.env.cr.fetchone()
        self.assertEqual(second_backup, first_backup)
