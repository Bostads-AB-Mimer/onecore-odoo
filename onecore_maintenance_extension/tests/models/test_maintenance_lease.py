from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import create_maintenance_request, create_lease


@tagged("onecore")
class TestMaintenanceLease(TransactionCase):
    def test_lease_cascade_delete_when_maintenance_request_deleted(self):
        """Test cascade delete when maintenance request is deleted."""
        request = create_maintenance_request(self.env)
        create_lease(self.env, maintenance_request_id=request.id)
        request.unlink()
        self.assertFalse(
            self.env["maintenance.lease"].search([("maintenance_request_id", "=", request.id)])
        )

    def test_name_includes_the_status_label(self):
        lease = create_lease(self.env, lease_id="705-023-04-0201/01", lease_status=0)
        self.assertEqual(lease.name, "705-023-04-0201/01 (Gällande)")

    def test_name_recomputes_when_lease_status_changes(self):
        """MIM-1954: name must never drift from lease_status_label again -
        the reported regression where Kontrakt kept showing "(Kommande)"
        while Kontraktsstatus already said "Gällande"."""
        lease = create_lease(self.env, lease_id="216-034-03-0101/01", lease_status=1)
        self.assertEqual(lease.name, "216-034-03-0101/01 (Kommande)")

        lease.lease_status = 0

        self.assertEqual(lease.name, "216-034-03-0101/01 (Gällande)")

    def test_name_falls_back_to_the_bare_lease_id_without_a_label(self):
        lease = create_lease(self.env, lease_id="705-023-04-0201/01", lease_status=99)
        self.assertEqual(lease.name, "705-023-04-0201/01")
