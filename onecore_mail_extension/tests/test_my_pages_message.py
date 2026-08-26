from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("onecore", "post_install", "-at_install")
class TestMyPagesMessage(TransactionCase):
    """MIM-1957: a Mina sidor message is published by existing in Odoo with the
    tenant_my_pages type — no provider send is involved."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # maintenance.request requires maintenance_request_category_id; category_1
        # is the fixture category loaded from maintenance.request.category.csv
        # (see onecore_maintenance_extension/tests/utils/test_utils.py).
        category_id = cls.env.ref("onecore_maintenance_extension.category_1").id
        cls.request = cls.env["maintenance.request"].create(
            {
                "name": "Trasig kran",
                "maintenance_request_category_id": category_id,
                "space_caption": "Lägenhet",
                "hidden_from_my_pages": False,
            }
        )
        cls.hidden_request = cls.env["maintenance.request"].create(
            {
                "name": "Dolt ärende",
                "maintenance_request_category_id": category_id,
                "space_caption": "Lägenhet",
                "hidden_from_my_pages": True,
            }
        )

    def _post(self, record, body="Hej!"):
        return self.env["mail.message"].create(
            {
                "model": "maintenance.request",
                "res_id": record.id,
                "body": body,
                "message_type": "tenant_my_pages",
            }
        )

    def test_my_pages_message_keeps_its_type(self):
        # No SMS/e-post is sent, so nothing can downgrade the type to a
        # failed_* variant the way tenant_sms/tenant_mail can.
        with patch.object(
            type(self.env["mail.message"]), "_log_my_pages_message"
        ) as log_mock:
            message = self._post(self.request)
        self.assertEqual(message.message_type, "tenant_my_pages")
        log_mock.assert_called_once()

    def test_my_pages_message_rejected_on_hidden_errand(self):
        # Digital tenant communication is closed for errands hidden from
        # Mimer.nu; the OWL guard is belt, this is braces.
        with self.assertRaises(UserError):
            self._post(self.hidden_request)
