"""Tests for migrations/19.0.1.0.8/post-migration.py (MIM-1954).

Before this fix, maintenance.lease.lease_id and maintenance.lease.name were
both populated from maintenance.lease.option.name — a display string with the
status label baked in, e.g. "705-023-04-0201/01 (Gällande)". That corrupted
lease_id (the identity sync_lease_status looks leases up by) meant those
leases could never be matched against OneCore's batch endpoint, so
lease_status was frozen at whatever it was when the case was created — which
also means a lease_id-corrupted row's baked-in name never had a chance to
disagree with its own lease_status: both were frozen together, in lockstep.

The visible symptom the migration also has to repair — Kontrakt showing a
stale status next to an already-updated Kontraktsstatus — could therefore
only happen on rows whose lease_id was *not* corrupted (e.g. leases created
through the "empty rental object" auto-fill path, which always wrote the raw
API leaseId): those could sync successfully and drift, because only
lease_status_label was wired up as a live compute, not the plain-Char name.

So the migration has to get both populations right in one pass: a
lease_id-corrupted row (lease_id repaired, name recomputed from the *newly
repaired* lease_id) and a lease_id-clean-but-name-stale row (lease_id
untouched, name recomputed from its already-correct lease_id). Both are
covered below.
"""

import importlib.util
import os

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


def _load_lease_suffix_migration():
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
class TestLeaseSuffixMigration(TransactionCase):
    def setUp(self):
        super().setUp()
        self.migration = _load_lease_suffix_migration()

    def _create_lease(self, lease_id):
        """A row whose lease_id may still carry the bug — name is left to
        whatever the (now computed) default produces; these tests only care
        about lease_id."""
        return self.env["maintenance.lease"].create(
            {
                "name": lease_id or "unnamed",
                "lease_id": lease_id,
                "lease_number": "12345",
                "lease_type": "Bostadskontrakt",
            }
        )

    def _create_frozen_row(self, lease_id, name, lease_status):
        """Simulate an already-persisted pre-fix row: lease_id/name/
        lease_status set directly via raw SQL, bypassing the compute chain
        entirely — exactly the decoupled, no-recompute-bookkeeping state a
        genuinely old database row is in."""
        lease = self.env["maintenance.lease"].create(
            {
                "name": name,
                "lease_id": lease_id,
                "lease_number": "12345",
                "lease_type": "Bostadskontrakt",
            }
        )
        # Resolve and flush this record's own computes first, so nothing is
        # left pending — otherwise the next ORM read would recompute name
        # from lease_status instead of returning the frozen value the raw
        # UPDATE just wrote, defeating the point of this helper.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE maintenance_lease SET lease_id = %s, lease_status = %s, name = %s "
            "WHERE id = %s",
            (lease_id, lease_status, name, lease.id),
        )
        self.env.invalidate_all()
        return lease

    # -- lease_id repair -----------------------------------------------

    def test_strips_the_status_label_suffix_from_lease_id(self):
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

    def test_skips_leases_without_a_lease_id(self):
        lease = self._create_lease(False)

        # Must not raise on a lease with no lease_id at all.
        self.migration.migrate(self.env.cr, "19.0.1.0.8")

        self.assertFalse(lease.lease_id)

    # -- name repair -----------------------------------------------------

    def test_recomputes_name_from_the_newly_repaired_lease_id(self):
        """A lease_id-corrupted row: lease_id and name were frozen together
        at creation, so name already agrees with lease_status — but it must
        be rebuilt from the *cleaned* lease_id, not just left as-is."""
        lease = self._create_frozen_row(
            lease_id="216-034-03-0101/01 (Gällande)",
            name="216-034-03-0101/01 (Gällande)",
            lease_status=0,
        )

        self.migration.migrate(self.env.cr, "19.0.1.0.8")

        self.assertEqual(lease.lease_id, "216-034-03-0101/01")
        self.assertEqual(lease.name, "216-034-03-0101/01 (Gällande)")

    def test_recomputes_a_name_left_disagreeing_with_its_own_status(self):
        """A lease_id-clean-but-name-stale row: lease_id was never corrupted
        (e.g. the auto-fill path), so the cron could and did refresh
        lease_status — but the old plain-Char name never followed along."""
        lease = self._create_frozen_row(
            lease_id="216-034-03-0101/01",
            name="216-034-03-0101/01 (Kommande)",
            lease_status=0,  # Gällande - already updated by the cron
        )

        self.migration.migrate(self.env.cr, "19.0.1.0.8")

        self.assertEqual(lease.lease_id, "216-034-03-0101/01")
        self.assertEqual(lease.name, "216-034-03-0101/01 (Gällande)")

    def test_leaves_an_already_correct_name_untouched(self):
        lease = self._create_frozen_row(
            lease_id="216-034-03-0101/01",
            name="216-034-03-0101/01 (Gällande)",
            lease_status=0,
        )

        self.migration.migrate(self.env.cr, "19.0.1.0.8")

        self.assertEqual(lease.name, "216-034-03-0101/01 (Gällande)")

    # -- idempotency -------------------------------------------------------

    def test_is_idempotent(self):
        lease = self._create_frozen_row(
            lease_id="216-034-03-0101/01 (Gällande)",
            name="216-034-03-0101/01 (Gällande)",
            lease_status=0,
        )

        self.migration.migrate(self.env.cr, "19.0.1.0.8")
        self.migration.migrate(self.env.cr, "19.0.1.0.8")

        self.assertEqual(lease.lease_id, "216-034-03-0101/01")
        self.assertEqual(lease.name, "216-034-03-0101/01 (Gällande)")
