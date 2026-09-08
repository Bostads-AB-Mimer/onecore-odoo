"""Tests for migrations/19.0.1.0.8/post-migration.py (MIM-1954).

Before the lease_id/name split (record_management_service._save_lease used to
copy maintenance.lease.option.name — a display string with the status label
baked in — straight into maintenance.lease.lease_id), every lease created
through the manual search-and-select flow ended up with a lease_id like
"705-023-04-0201/01 (Gällande)". sync_lease_status sends lease_id to OneCore's
POST /leases/batch as the lookup key, so those leases could never be matched
and their kontraktsstatus/last_debit_date silently stopped refreshing. This
migration repairs the already-persisted rows.
"""

import importlib.util
import os

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


def _load_lease_id_suffix_migration():
    """Load migrations/19.0.1.0.8/post-migration.py by path.

    The directory name is not a valid Python identifier, so it has to be
    loaded from its file path rather than imported normally — same idiom as
    the other migration tests in this suite.
    """
    module_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    path = os.path.join(module_root, "migrations", "19.0.1.0.8", "post-migration.py")
    spec = importlib.util.spec_from_file_location("mim_1954_post_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("onecore")
class TestLeaseIdSuffixMigration(TransactionCase):
    def setUp(self):
        super().setUp()
        self.migration = _load_lease_id_suffix_migration()

    def _create_lease(self, lease_id):
        return self.env["maintenance.lease"].create(
            {
                "name": lease_id or "unnamed",
                "lease_id": lease_id,
                "lease_number": "12345",
                "lease_type": "Bostadskontrakt",
            }
        )

    def test_strips_the_status_label_suffix(self):
        lease = self._create_lease("705-023-04-0201/01 (Gällande)")

        self.migration.migrate(self.env.cr, "19.0.1.0.8")

        self.assertEqual(lease.lease_id, "705-023-04-0201/01")

    def test_handles_every_known_status_label(self):
        leases = {
            label: self._create_lease(f"705-023-04-0{i}01/01 ({label})")
            for i, label in enumerate(
                ["Gällande", "Kommande", "Uppsagt", "Upphört", "Okänd status"]
            )
        }

        self.migration.migrate(self.env.cr, "19.0.1.0.8")

        for label, lease in leases.items():
            self.assertNotIn(label, lease.lease_id)
            self.assertFalse(lease.lease_id.endswith(")"))

    def test_leaves_an_already_clean_lease_id_untouched(self):
        lease = self._create_lease("705-023-04-0201/01")

        self.migration.migrate(self.env.cr, "19.0.1.0.8")

        self.assertEqual(lease.lease_id, "705-023-04-0201/01")

    def test_is_idempotent(self):
        lease = self._create_lease("705-023-04-0201/01 (Gällande)")

        self.migration.migrate(self.env.cr, "19.0.1.0.8")
        self.migration.migrate(self.env.cr, "19.0.1.0.8")

        self.assertEqual(lease.lease_id, "705-023-04-0201/01")

    def test_skips_leases_without_a_lease_id(self):
        lease = self._create_lease(False)

        # Must not raise on a lease with no lease_id at all.
        self.migration.migrate(self.env.cr, "19.0.1.0.8")

        self.assertFalse(lease.lease_id)
