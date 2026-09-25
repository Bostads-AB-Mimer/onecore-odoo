from unittest.mock import ANY, MagicMock, patch

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

    def _post(self, record, body="Hej!", message_type="tenant_my_pages"):
        return self.env["mail.message"].create(
            {
                "model": "maintenance.request",
                "res_id": record.id,
                "body": body,
                "message_type": message_type,
            }
        )

    def test_my_pages_message_keeps_its_type(self):
        # No SMS/e-post is sent, so nothing can downgrade the type to a
        # failed_* variant the way tenant_sms/tenant_mail can.
        with patch.object(
            type(self.env["mail.message"]),
            "_log_my_pages_message",
            autospec=True,
        ) as log_mock:
            message = self._post(self.request)
        self.assertEqual(message.message_type, "tenant_my_pages")
        # Pin the call contract: work order code carries the "od-" prefix
        # OneCore expects, and the body/user are passed through unchanged.
        # This is a cross-repo contract with no other guard in this repo.
        log_mock.assert_called_once_with(
            ANY, f"od-{self.request.id}", ANY, "Hej!", self.env.user.name
        )

    def test_log_failure_does_not_downgrade_message_type(self):
        # A Mina sidor message is published by existing in Odoo with this type,
        # so a failed OneCore log call must never change it — that would retract
        # a message the tenant has already received. Unlike the test above,
        # this exercises the real _log_my_pages_message try/except by failing
        # one level lower (get_core_api), so a regression that starts
        # downgrading message_type inside that except block would be caught.
        with patch.object(
            type(self.env["mail.message"]),
            "get_core_api",
            side_effect=Exception("core unavailable"),
        ):
            message = self._post(self.request)
        self.assertEqual(message.message_type, "tenant_my_pages")

    def test_my_pages_message_rejected_on_hidden_errand(self):
        # Digital tenant communication is closed for errands hidden from
        # Mimer.nu; the OWL guard is belt, this is braces.
        with self.assertRaises(UserError):
            self._post(self.hidden_request)

    def test_comment_allowed_on_hidden_errand(self):
        # The hidden-from-Mimer.nu guard is scoped to tenant_my_pages only —
        # internal log notes (message_type "comment") must keep working on a
        # hidden errand. Regression guard for the server-visible half of the
        # note-mode leak fixed in postData (tenant_composer_patch.js): the
        # JS-side leak routed internal notes to tenant_my_pages, which would
        # have made this raise where it must not.
        message = self._post(self.hidden_request, message_type="comment")
        self.assertEqual(message.message_type, "comment")

    def test_log_payload_uses_onecore_key_names(self):
        # OneCore validates these exact camelCase keys; a rename here would pass
        # every test in this repo and 400 in production.
        api = MagicMock()
        with patch.object(
            type(self.env["mail.message"]), "get_core_api", return_value=api
        ):
            self._post(self.request, body="Hej!")
        args, kwargs = api.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "/work-orders/log-my-pages-message")
        self.assertEqual(
            set(kwargs["json"]),
            {"workOrderCode", "contactCode", "text", "triggeredByUser"},
        )
        self.assertEqual(kwargs["json"]["workOrderCode"], f"od-{self.request.id}")

    def test_sms_payload_includes_work_order_code(self):
        # MIM-1957: lets the communication log link the SMS row to the errand.
        with patch.object(
            type(self.env["mail.message"]), "_send_sms", return_value={}
        ) as send_mock:
            self.env["mail.message"].create(
                {
                    "model": "maintenance.request",
                    "res_id": self.request.id,
                    "body": "Hej!",
                    "message_type": "tenant_sms",
                }
            )
        self.assertEqual(
            send_mock.call_args.kwargs.get("work_order_code"),
            f"od-{self.request.id}",
        )
