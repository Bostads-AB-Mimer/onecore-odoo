from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("onecore", "post_install", "-at_install")
class TestTenantAuthorName(TransactionCase):
    """MIM-2040: the tenant must see who answered, not which of us typed it.

    onecore_tenant_author_name is the name Mina sidor shows beside an outbound
    message. It is captured at write time so the history stays true even after
    a request is reassigned to another resource group.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        category_id = cls.env.ref("onecore_maintenance_extension.category_1").id
        internal_group = cls.env.ref("base.group_user")
        # Mimer's handläggare are equipment managers; without that group, base
        # maintenance's equipment_request_rule_user limits a plain internal user
        # to requests they own or follow, and posting is denied outright.
        manager_group = cls.env.ref("maintenance.group_equipment_manager")
        ext_group = cls.env.ref(
            "onecore_maintenance_extension.group_external_contractor"
        )
        # A dedicated internal user is used (rather than the raw TransactionCase
        # env, which runs as base.user_root) because maintenance.xml explicitly
        # adds user_root to group_external_contractor, so the default test env
        # is itself considered an external contractor for has_group() checks.
        cls.internal_user = cls.env["res.users"].create(
            {
                "name": "Sebastian Handläggare",
                "login": "internal_author_test",
                "group_ids": [(6, 0, [internal_group.id, manager_group.id])],
            }
        )
        cls.external_user = cls.env["res.users"].create(
            {
                "name": "Erika Entreprenör",
                "login": "ext_author_test",
                "group_ids": [(6, 0, [internal_group.id, ext_group.id])],
            }
        )
        # An external contractor only reaches a request through
        # maintenance_request_rule_external_contractor_group_readonly, whose
        # domain is [('maintenance_team_id.member_ids', 'in', [user.id])] — so
        # the team membership below is what makes the contractor tests able to
        # post at all.
        cls.team = cls.env["maintenance.team"].create(
            {
                "name": "Städbolaget AB",
                "member_ids": [(6, 0, [cls.external_user.id])],
            }
        )
        cls.request = cls.env["maintenance.request"].create(
            {
                "name": "Trasig kran",
                "maintenance_request_category_id": category_id,
                "space_caption": "Lägenhet",
                "hidden_from_my_pages": False,
                "maintenance_team_id": cls.team.id,
            }
        )

    def _post(self, user, record=None, message_type="tenant_my_pages", body="Hej!"):
        """Post as `user`, with the Mina sidor log call to OneCore stubbed out."""
        record = self.request if record is None else record
        messages = self.env["mail.message"].with_user(user)
        with patch.object(
            type(self.env["mail.message"]),
            "_log_my_pages_message",
            autospec=True,
        ):
            return messages.create(
                {
                    "model": "maintenance.request",
                    "res_id": record.id,
                    "body": body,
                    "message_type": message_type,
                }
            )

    def test_internal_user_is_attributed_to_mimer(self):
        # The bug in the ticket: the tenant saw "Sebastian" rather than Mimer.
        message = self._post(self.internal_user)
        self.assertEqual(message.onecore_tenant_author_name, "Mimer")

    def test_external_contractor_names_the_resource_group(self):
        message = self._post(self.external_user)
        self.assertEqual(
            message.onecore_tenant_author_name, "Mimers Leverantör - Städbolaget AB"
        )

    def test_contractor_falls_back_to_bare_label_without_a_readable_request(self):
        # maintenance_team_id is required=True with a default, so a request
        # always has a team; the only way to reach this branch is a message
        # whose thread the acting contractor cannot read. The label must then
        # degrade to the bare form, never to a dangling "Mimers Leverantör - ".
        name = (
            self.env["mail.message"]
            .with_user(self.external_user)
            ._tenant_facing_author_name(False)
        )
        self.assertEqual(name, "Mimers Leverantör")

    def test_superuser_is_attributed_to_mimer(self):
        # security/maintenance.xml puts base.user_root in
        # group_external_contractor, so OdooBot passes the has_group() test. It
        # is not a supplier: anything it posts is Mimer's own automation, and a
        # tenant must never be told a resource group answered because a job ran
        # as the superuser.
        message = self._post(self.env.ref("base.user_root"))
        self.assertEqual(message.onecore_tenant_author_name, "Mimer")

    def test_receipt_to_tenant_is_attributed(self):
        # receipt_to_tenant (MIM-1960) is deliberately not tenant_-prefixed, so
        # it misses the dispatch branch — but the tenant does see it on Mina
        # sidor, so it needs the label just as much.
        message = self._post(self.internal_user, message_type="receipt_to_tenant")
        self.assertEqual(message.onecore_tenant_author_name, "Mimer")

    def test_tenant_message_gets_no_author_name(self):
        # from_tenant is the tenant's own message; Mina sidor renders "Du".
        message = self._post(self.internal_user, message_type="from_tenant")
        self.assertFalse(message.onecore_tenant_author_name)

    def test_internal_note_gets_no_author_name(self):
        # Internal log notes never reach the tenant.
        message = self._post(self.internal_user, message_type="comment")
        self.assertFalse(message.onecore_tenant_author_name)

    def test_failed_send_keeps_the_author_name(self):
        # create() rewrites message_type to failed_tenant_mail when the send
        # fails. The label is captured from the type the caller asked for, so
        # the rewrite must not leave the message unattributed.
        with patch.object(
            type(self.env["mail.message"]), "_send_email", return_value=None
        ):
            message = self._post(self.internal_user, message_type="tenant_mail")
        self.assertEqual(message.message_type, "failed_tenant_mail")
        self.assertEqual(message.onecore_tenant_author_name, "Mimer")
