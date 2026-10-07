"""Tests for migrations/19.0.1.0.13/post-migration.py: performed_date
("Utfört datum") backfilled from the stage history.

The stage moves are written the way the chatter stores them
(mail.message + mail.tracking.value on stage_id), with dates chosen by the
test, and the requests are put in their stage with SQL, as an old database
has them, so no workflow stamps or clears performed_date on the way.
"""

import importlib.util
import os
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..utils.test_utils import create_maintenance_request

STAGES = {
    "started": "maintenance.stage_3",  # Påbörjad
    "performed": "maintenance.stage_5",  # Utförd
    "closed": "maintenance.stage_6",  # Avslutad
    "returned": "onecore_maintenance_extension.stage_atersand",
}


def _load_migration():
    """Load migrations/19.0.1.0.13/post-migration.py by file path: migration
    directories are not valid package names (same idiom as
    test_priority_migration.py)."""
    module_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    path = os.path.join(module_root, "migrations", "19.0.1.0.13", "post-migration.py")
    spec = importlib.util.spec_from_file_location("performed_date_backfill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("onecore")
class TestPerformedDateBackfill(TransactionCase):
    def setUp(self):
        super().setUp()
        self.migration = _load_migration()
        self.stage = {key: self.env.ref(xml_id).id for key, xml_id in STAGES.items()}
        self.stage_field = self.env["ir.model.fields"]._get("maintenance.request", "stage_id")
        self.t0 = fields.Datetime.now().replace(microsecond=0) - timedelta(days=200)

    def _request(self, stage, performed_date=None):
        """A request sitting in ``stage``, set with SQL as an old database
        has it."""
        request = create_maintenance_request(self.env)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE maintenance_request SET stage_id = %s, performed_date = %s WHERE id = %s",
            (self.stage[stage], performed_date, request.id),
        )
        self.env.invalidate_all()
        return request

    def _move(self, request, stage, days):
        """A tracked move into ``stage`` (a key of STAGES, or a raw stage id),
        ``days`` after t0."""
        when = self.t0 + timedelta(days=days)
        stage_id = self.stage.get(stage, stage)
        message = self.env["mail.message"].create(
            {
                "model": "maintenance.request",
                "res_id": request.id,
                "message_type": "notification",
                "date": when,
            }
        )
        self.env["mail.tracking.value"].create(
            {
                "field_id": self.stage_field.id,
                "mail_message_id": message.id,
                "new_value_integer": stage_id,
            }
        )
        return when

    def _run(self):
        self.env.flush_all()
        self.migration.migrate(self.env.cr, "19.0.1.0.12")
        self.env.invalidate_all()

    def test_dates_requests_from_their_last_move_into_utford(self):
        performed = self._request("performed")
        performed_at = self._move(performed, "performed", 10)

        # Performed, reopened, performed again, closed: the second time counts.
        twice = self._request("closed")
        self._move(twice, "performed", 10)
        self._move(twice, "started", 20)
        performed_again_at = self._move(twice, "performed", 30)
        self._move(twice, "closed", 40)

        # Closed, then reopened straight into Utförd.
        reperformed = self._request("performed")
        self._move(reperformed, "performed", 10)
        self._move(reperformed, "closed", 20)
        reperformed_at = self._move(reperformed, "performed", 30)

        self._run()

        self.assertEqual(performed.performed_date, performed_at)
        self.assertEqual(twice.performed_date, performed_again_at)
        self.assertEqual(reperformed.performed_date, reperformed_at)

    def test_same_second_moves_follow_the_message_order(self):
        """Assigning a resource moves the request to Resurs tilldelad, and an
        integration can set Utförd in the same second. The later message
        wins."""
        request = self._request("performed")
        self._move(request, "started", 10)
        performed_at = self._move(request, "performed", 10)

        self._run()

        self.assertEqual(request.performed_date, performed_at)

    def test_ignores_moves_into_stages_that_no_longer_exist(self):
        """Duplicate stages merged away by hooks._repair_duplicate_stages
        leave tracking values pointing at deleted ids. They must not count as
        a reopen."""
        missing_stage_id = self.env["maintenance.stage"].search([], order="id desc", limit=1).id + 1000
        request = self._request("closed")
        performed_at = self._move(request, "performed", 10)
        self._move(request, missing_stage_id, 20)

        self._run()

        self.assertEqual(request.performed_date, performed_at)

    def test_leaves_what_the_workflow_would_leave_empty(self):
        """Reopened after Utförd (to an active stage or Återsänd) and closed
        without passing it again, closed without ever passing Utförd, never
        tracked, and still active: the workflow clears or never stamps the
        date for all of them."""
        reopened = self._request("closed")
        self._move(reopened, "performed", 10)
        self._move(reopened, "started", 20)
        self._move(reopened, "closed", 30)

        returned = self._request("closed")
        self._move(returned, "performed", 10)
        self._move(returned, "returned", 20)
        self._move(returned, "closed", 30)

        never_performed = self._request("closed")
        self._move(never_performed, "closed", 10)

        never_tracked = self._request("performed")

        still_open = self._request("started")
        self._move(still_open, "performed", 10)
        self._move(still_open, "started", 20)

        self._run()

        for request in (reopened, returned, never_performed, never_tracked, still_open):
            with self.subTest(request=request.id):
                self.assertFalse(request.performed_date)

    def test_keeps_an_existing_date(self):
        kept = self.t0 + timedelta(days=99)
        dated = self._request("performed", performed_date=kept)
        self._move(dated, "performed", 10)

        self._run()

        self.assertEqual(dated.performed_date, kept)

    def test_second_run_changes_nothing(self):
        request = self._request("closed")
        self._move(request, "performed", 10)
        self._run()
        first = request.performed_date

        self._run()

        self.assertTrue(first)
        self.assertEqual(request.performed_date, first)
