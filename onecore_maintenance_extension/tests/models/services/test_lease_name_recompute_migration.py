"""Tests for migrations/19.0.1.0.9/post-migration.py (MIM-1954).

maintenance.lease.name used to be a plain Char baked once at creation, so an
existing lease's persisted name could disagree with its own lease_status
after sync_lease_status refreshed the latter (see the reported regression:
Kontrakt showed "216-034-03-0101/01 (Kommande)" while Kontraktsstatus already
said "Gällande"). name is now a stored compute
(models/maintenance_lease.py:_compute_name), which keeps it in sync from now
on — this migration repairs rows that were already persisted with the old,
frozen value before that change shipped.
"""

import importlib.util
import os

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


def _load_lease_name_recompute_migration():
    """Load migrations/19.0.1.0.9/post-migration.py by path.

    The directory name is not a valid Python identifier, so it has to be
    loaded from its file path rather than imported normally — same idiom as
    the other migration tests in this suite.
    """
    module_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    path = os.path.join(module_root, "migrations", "19.0.1.0.9", "post-migration.py")
    spec = importlib.util.spec_from_file_location("mim_1954_name_recompute", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("onecore")
class TestLeaseNameRecomputeMigration(TransactionCase):
    def setUp(self):
        super().setUp()
        self.migration = _load_lease_name_recompute_migration()

    def _create_lease_with_frozen_name(self, name, lease_id, lease_status):
        """Simulate a pre-fix row: name set directly, disagreeing with the
        status it is later given — exactly what the old plain-Char name
        allowed and the new compute cannot."""
        lease = self.env["maintenance.lease"].create(
            {
                "name": name,
                "lease_id": lease_id,
                "lease_number": "12345",
                "lease_type": "Bostadskontrakt",
            }
        )
        # Resolve and flush the record's own computes first, so nothing is
        # left pending — otherwise the next ORM read of name would recompute
        # it from the fresh lease_status below instead of returning the
        # stale value the raw UPDATE just wrote, defeating the point of this
        # helper (a pre-fix row whose name has already fully decoupled from
        # its own lease_status, with no recompute bookkeeping attached).
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE maintenance_lease SET lease_status = %s, name = %s WHERE id = %s",
            (lease_status, name, lease.id),
        )
        self.env.invalidate_all()
        return lease

    def test_recomputes_a_name_left_disagreeing_with_its_status(self):
        lease = self._create_lease_with_frozen_name(
            name="216-034-03-0101/01 (Kommande)",
            lease_id="216-034-03-0101/01",
            lease_status=0,  # Gällande - already updated by the cron
        )
        self.assertEqual(lease.name, "216-034-03-0101/01 (Kommande)")

        self.migration.migrate(self.env.cr, "19.0.1.0.9")
        lease.invalidate_recordset()

        self.assertEqual(lease.name, "216-034-03-0101/01 (Gällande)")

    def test_is_idempotent(self):
        lease = self._create_lease_with_frozen_name(
            name="216-034-03-0101/01 (Kommande)",
            lease_id="216-034-03-0101/01",
            lease_status=0,
        )

        self.migration.migrate(self.env.cr, "19.0.1.0.9")
        self.migration.migrate(self.env.cr, "19.0.1.0.9")
        lease.invalidate_recordset()

        self.assertEqual(lease.name, "216-034-03-0101/01 (Gällande)")

    def test_leaves_an_already_correct_name_untouched(self):
        lease = self._create_lease_with_frozen_name(
            name="216-034-03-0101/01 (Gällande)",
            lease_id="216-034-03-0101/01",
            lease_status=0,
        )

        self.migration.migrate(self.env.cr, "19.0.1.0.9")
        lease.invalidate_recordset()

        self.assertEqual(lease.name, "216-034-03-0101/01 (Gällande)")
