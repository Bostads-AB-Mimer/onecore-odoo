import logging

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

# EXPECTED_TENANT_FACING lives next to the frozenset it guards, in
# models/mail_message.py, because a developer adding a message_type is already
# editing that file and has no reason to open this one.
from ..models.mail_message import (
    EXPECTED_TENANT_FACING,
    TENANT_FACING_MESSAGE_TYPES,
)

_logger = logging.getLogger(__name__)


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

    def _post(
        self,
        user,
        record=None,
        message_type="tenant_my_pages",
        body="Hej!",
        model="maintenance.request",
        author_partner=None,
    ):
        """Post as `user`, with the Mina sidor log call to OneCore stubbed out."""
        record = self.request if record is None else record
        messages = self.env["mail.message"].with_user(user)
        values = {
            "model": model,
            "res_id": record.id,
            "body": body,
            "message_type": message_type,
        }
        if author_partner is not None:
            values["author_id"] = author_partner.id
        with patch.object(
            type(self.env["mail.message"]),
            "_log_my_pages_message",
            autospec=True,
        ):
            return messages.create(values)

    def _live_message_types(self):
        """The message_type selection as installed, minus user_notification.

        Same accessor as tests/test_log_category.py — get_values() returns the
        selection after selection_add merging.
        """
        return set(
            self.env["mail.message"]._fields["message_type"].get_values(self.env)
        ) - {"user_notification"}

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
            ._tenant_facing_author_name(self.external_user)
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

    def test_message_post_attributes_the_same_way_as_a_bare_create(self):
        # Production never calls mail.message.create() directly: it goes through
        # maintenance.request.message_post(), which wraps the create in sudo()
        # and fills author_id itself. Every other test here creates the message
        # directly, so this one proves the real path reaches the same label
        # rather than assuming sudo() leaves the classification alone.
        with patch.object(
            type(self.env["mail.message"]),
            "_log_my_pages_message",
            autospec=True,
        ):
            message = self.request.with_user(self.external_user).message_post(
                body="Hej!",
                message_type="tenant_my_pages",
                subtype_xmlid="mail.mt_note",
            )
        self.assertEqual(
            message.onecore_tenant_author_name, "Mimers Leverantör - Städbolaget AB"
        )

    def test_explicit_author_decides_the_label_not_the_acting_user(self):
        # message_post(author_id=...) posts on someone else's behalf. The
        # backfill has only author_id to go on, so the write path has to agree
        # with it — otherwise one message is labelled one way today and the
        # other way by a re-run of the migration.
        message = self._post(
            self.internal_user, author_partner=self.external_user.partner_id
        )
        self.assertEqual(
            message.onecore_tenant_author_name, "Mimers Leverantör - Städbolaget AB"
        )

    def test_unresolvable_author_falls_back_to_the_acting_user(self):
        # A bare res.partner with no user behind it must not quietly drop the
        # contractor label to "Mimer".
        partner = self.env["res.partner"].create({"name": "Ingen användare"})
        message = self._post(self.external_user, author_partner=partner)
        self.assertEqual(
            message.onecore_tenant_author_name, "Mimers Leverantör - Städbolaget AB"
        )

    def test_a_message_on_another_model_borrows_no_resource_group(self):
        # The resource group comes from the maintenance.request the message
        # sits on, so the lookup is keyed on model as well as res_id: ids
        # collide across models, and keying on res_id alone let a tenant-facing
        # message posted on anything else be labelled with whichever request
        # happened to share its id.
        #
        # This asserts the gate, not the collision — arranging a partner and a
        # request with the same id would mean restarting a sequence, which
        # PostgreSQL does not roll back with the test transaction.
        #
        # sudo() only to get past the mail.message create rule: an external
        # contractor may post on a maintenance.request and nothing else, and it
        # is the label, not the ACL, under test. uid is unchanged, so the
        # contractor/Mimer classification is still the real one.
        # receipt_to_tenant rather than a tenant_* type keeps create()'s
        # SMS/e-post dispatch out of it.
        partner = self.env["res.partner"].create({"name": "Annan modell"})
        message = (
            self.env["mail.message"]
            .with_user(self.external_user)
            .sudo()
            .create(
                {
                    "model": "res.partner",
                    "res_id": partner.id,
                    "body": "Hej!",
                    "message_type": "receipt_to_tenant",
                }
            )
        )
        self.assertEqual(message.onecore_tenant_author_name, "Mimers Leverantör")

    def test_every_message_type_is_classified_as_tenant_facing_or_not(self):
        """Fails the build when a new message_type is added without deciding
        whether a tenant reads it. See the EXPECTED_TENANT_FACING comment.

        One-directional in the same way as test_log_category.py's twin: the
        guard that matters is "no live type is missing from the map". `sms` and
        `snailmail` arrive through auto_install rather than this repo's -i
        list, which differs between run_tests.sh and CI, so the other direction
        is logged instead of asserted.
        """
        live_types = self._live_message_types()
        unclassified = live_types - set(EXPECTED_TENANT_FACING)
        self.assertFalse(
            unclassified,
            f"message_type(s) {sorted(unclassified)} are not in "
            "EXPECTED_TENANT_FACING (onecore_mail_extension/models/"
            "mail_message.py). A new tenant-facing type that is missed keeps "
            "its sender unlabelled, which the work-order adapter silently "
            'renders as "Mimer" — decide whether a tenant reads it, then '
            "list it there and in TENANT_FACING_MESSAGE_TYPES.",
        )
        not_installed = set(EXPECTED_TENANT_FACING) - live_types
        if not_installed:
            _logger.info(
                "EXPECTED_TENANT_FACING lists message_type(s) that are not "
                "installed in this database, skipped: %s",
                sorted(not_installed),
            )

    def test_expected_tenant_facing_matches_the_capture_list(self):
        # The map above is the documentation; TENANT_FACING_MESSAGE_TYPES is
        # what create() actually branches on. They must not drift.
        live_types = self._live_message_types()
        expected = {
            message_type
            for message_type, tenant_facing in EXPECTED_TENANT_FACING.items()
            if tenant_facing and message_type in live_types
        }
        self.assertEqual(expected, set(TENANT_FACING_MESSAGE_TYPES) & live_types)
