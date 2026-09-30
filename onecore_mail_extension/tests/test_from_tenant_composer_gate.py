from odoo.tests import HttpCase, tagged
from odoo.tests.common import JsonRpcException


@tagged("onecore", "post_install", "-at_install")
class TestFromTenantComposerGate(HttpCase):
    """MIM-2040 (extra): only work-order may write a from_tenant message."""

    def setUp(self):
        super().setUp()
        self.user = self.env["res.users"].create(
            {
                "name": "Sebastian Handläggare",
                "login": "gate_handlaggare",
                "password": "gate_handlaggare",
                "group_ids": [
                    (6, 0, [
                        self.env.ref("base.group_user").id,
                        self.env.ref("maintenance.group_equipment_manager").id,
                    ])
                ],
            }
        )
        self.request = self.env["maintenance.request"].create(
            {
                "name": "Trasig kran",
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": "Lägenhet",
            }
        )
        self.authenticate("gate_handlaggare", "gate_handlaggare")

    def _post(self, message_type):
        return self.make_jsonrpc_request(
            "/mail/message/post",
            {
                "thread_model": "maintenance.request",
                "thread_id": self.request.id,
                "post_data": {"body": "Hej", "message_type": message_type},
            },
        )

    def test_composer_cannot_post_from_tenant(self):
        with self.assertRaises(JsonRpcException):
            self._post("from_tenant")
        self.assertFalse(
            self.request.message_ids.filtered(
                lambda m: m.message_type == "from_tenant"
            )
        )

    def test_composer_still_posts_ordinary_messages(self):
        result = self._post("comment")
        self.assertTrue(result["message_id"])
