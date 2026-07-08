from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...models.services.record_management_service import RecordManagementService
from ..utils.test_utils import (
    create_maintenance_request,
    create_rental_property,
)


@tagged("onecore")
class TestRemoveUnlinkRecord(TransactionCase):
    def _rental_property(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        return create_rental_property(self.env, maintenance_request_id=request.id)

    def test_unlink_record_deletes_permanent_record(self):
        rp = self._rental_property()
        rp_id = rp.id
        RecordManagementService(self.env).unlink_record(rp)
        self.assertFalse(self.env["maintenance.rental.property"].browse(rp_id).exists())

    def test_unlink_record_best_effort_on_blocked_delete(self):
        rp = self._rental_property()
        rp_id = rp.id
        with patch.object(type(rp), "unlink", side_effect=Exception("blocked")):
            # Must not raise.
            RecordManagementService(self.env).unlink_record(rp)
        self.assertTrue(self.env["maintenance.rental.property"].browse(rp_id).exists())

    def test_unlink_record_keeps_transaction_usable_after_blocked_delete(self):
        """A blocked delete is a foreign-key violation, which aborts the whole
        transaction. The savepoint inside unlink_record is what lets the caller
        carry on afterwards — without it the caller's remaining work (further
        unlinks, the chatter note) dies on InFailedSqlTransaction and the change
        the user just confirmed is rolled back."""
        rp = self._rental_property()

        def abort_transaction(*args, **kwargs):
            # Any failing statement puts the transaction in the aborted state a
            # real FK violation would.
            self.env.cr.execute("SELECT 1 / 0")

        with patch.object(type(rp), "unlink", side_effect=abort_transaction):
            RecordManagementService(self.env).unlink_record(rp)

        # The caller must still be able to touch the database.
        follow_up = self._rental_property()
        self.assertTrue(follow_up.exists())

    def test_unlink_record_noop_on_empty(self):
        empty = self.env["maintenance.rental.property"].browse(False)
        RecordManagementService(self.env).unlink_record(empty)  # must not raise
