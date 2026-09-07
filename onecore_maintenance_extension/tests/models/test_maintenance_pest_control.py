"""The "Spärr skadedjur" flag is a stored snapshot, not a computed value.

It used to be computed per record with a live OneCore call, which is why it
could only ever appear on the form (MIM-1959). It is now written by
OneCoreFlagSyncService - on the create path and by the cron - so the kanban can
render it without one API call per card. These tests pin the field's shape; the
sync behaviour lives in tests/models/services/test_onecore_flag_sync_service.py.
"""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..utils.test_utils import create_maintenance_request, create_rental_property


@tagged("onecore")
class TestRequiresPestControlField(TransactionCase):
    def setUp(self):
        super().setUp()
        self.rental_property = create_rental_property(
            self.env, rental_property_id="705-022-04-0201"
        )
        self.request = create_maintenance_request(
            self.env,
            space_caption="Lägenhet",
            rental_property_id=self.rental_property.id,
        )

    def test_defaults_to_false(self):
        self.assertFalse(self.request.requires_pest_control)

    def test_is_stored(self):
        field = self.env["maintenance.request"]._fields["requires_pest_control"]
        self.assertTrue(field.store)
        self.assertFalse(field.compute)

    def test_survives_a_reread(self):
        """A stored value must not be recomputed away on the next read."""
        self.request.sudo().write({"requires_pest_control": True})
        self.request.invalidate_recordset(["requires_pest_control"])
        self.assertTrue(self.request.requires_pest_control)

    def test_is_searchable(self):
        """Storing it is what lets the list view filter and group on it."""
        self.request.sudo().write({"requires_pest_control": True})
        found = self.env["maintenance.request"].search(
            [("requires_pest_control", "=", True), ("id", "=", self.request.id)]
        )
        self.assertEqual(found, self.request)
