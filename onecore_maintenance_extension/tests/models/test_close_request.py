"""Tests for the tenant's close request (MIM-2036).

A tenant can no longer close an Odoo case from Mina sidor. They ask, via
request_close_from_tenant, and an Odoo user decides: "Avsluta ärendet"
(action_accept_close_request) or "Avslå" with a reason (the decline wizard).
Moving the case to Avslutad any other way also resolves the request.
"""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...models.constants import (
    CLOSE_REQUEST_DECLINED_MESSAGE_TYPE,
    CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE,
)


@tagged("onecore")
class TestCloseRequestMessageTypes(TransactionCase):
    def test_types_are_registered_on_mail_message(self):
        # Assert on the constants, not literals, so renaming one side without
        # the other (constants.py vs onecore_mail_extension) fails here.
        selection = dict(self.env["mail.message"]._fields["message_type"].selection)
        self.assertIn(CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE, selection)
        self.assertIn(CLOSE_REQUEST_DECLINED_MESSAGE_TYPE, selection)

    def test_types_are_not_outbound_tenant_dispatch_types(self):
        # Every tenant_* type sends a real SMS/e-post in mail.message.create.
        for message_type in (
            CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE,
            CLOSE_REQUEST_DECLINED_MESSAGE_TYPE,
        ):
            with self.subTest(message_type=message_type):
                self.assertFalse(message_type.startswith("tenant_"))
