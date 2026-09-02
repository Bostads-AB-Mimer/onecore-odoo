from odoo.fields import Domain
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tools.discuss import Store

from ..models.mail_message import (
    LOG_CATEGORY_COMMUNICATION,
    LOG_CATEGORY_EVENT,
    LOG_CATEGORY_INTERNAL_NOTE,
)

# Every message_type the chatter can show, mapped to the category it MUST fall
# into. `user_notification` is excluded because base _message_fetch filters it
# out before it can reach the chatter.
#
# This map is deliberately exhaustive: test_every_message_type_is_classified
# fails when a new type is added to the selection without being listed here.
# That is the guard against a new type silently landing in Kommunikation, i.e.
# in the filter a handläggare reads as "the tenant conversation".
EXPECTED_CATEGORIES = {
    # Base Odoo types (addons/mail/models/mail_message.py:119)
    "email": LOG_CATEGORY_COMMUNICATION,
    "comment": LOG_CATEGORY_COMMUNICATION,  # public subtype; see note below
    "email_outgoing": LOG_CATEGORY_COMMUNICATION,
    "notification": LOG_CATEGORY_EVENT,
    "auto_comment": LOG_CATEGORY_COMMUNICATION,
    "out_of_office": LOG_CATEGORY_COMMUNICATION,
    # ONECore types (onecore_mail_extension)
    "from_tenant": LOG_CATEGORY_COMMUNICATION,
    "receipt_to_tenant": LOG_CATEGORY_COMMUNICATION,
    "tenant_sms": LOG_CATEGORY_COMMUNICATION,
    "tenant_mail": LOG_CATEGORY_COMMUNICATION,
    "tenant_mail_and_sms": LOG_CATEGORY_COMMUNICATION,
    "failed_tenant_sms": LOG_CATEGORY_COMMUNICATION,
    "failed_tenant_mail": LOG_CATEGORY_COMMUNICATION,
    "failed_tenant_mail_and_sms": LOG_CATEGORY_COMMUNICATION,
    "tenant_mail_ok_and_sms_failed": LOG_CATEGORY_COMMUNICATION,
    "tenant_mail_failed_and_sms_ok": LOG_CATEGORY_COMMUNICATION,
    # base `sms` and `snailmail` addons (auto_install=True on `mail`+`iap_mail`,
    # both already satisfied here) add these two selection values even though
    # onecore doesn't use either module directly. Neither is "comment" nor
    # "notification", so the rule table's catch-all already puts them in
    # Kommunikation — correct, since both represent outbound communication to
    # a partner.
    "sms": LOG_CATEGORY_COMMUNICATION,
    "snailmail": LOG_CATEGORY_COMMUNICATION,
}

# `comment` is the one type whose category depends on the subtype: with an
# internal subtype (mail.mt_note = "Logga notering") it is an intern notering,
# with a public one (mail.mt_comment) it is kommunikation. EXPECTED_CATEGORIES
# lists its public reading; the internal one is covered by
# test_log_note_is_internal_note.


@tagged("onecore", "post_install", "-at_install")
class TestOneCoreLogCategory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # res.partner, not maintenance.request: categorisation reads only
        # message_type and subtype_id, so it is model-agnostic, while
        # maintenance.request.create() in this repo calls out to OneCore
        # (management-area population, creation SMS) — slow and network-
        # dependent for no coverage gain. Same choice as test_pin_message.py.
        cls.thread = cls.env["res.partner"].create({"name": "MIM-1956 Test"})
        cls.note_subtype = cls.env.ref("mail.mt_note")
        cls.comment_subtype = cls.env.ref("mail.mt_comment")

    def _message(self, message_type, subtype=None):
        """Create a chatter message with the given type, safely.

        CRITICAL: do not pass a tenant_* type to create(). OneCoreMailMessage
        .create() intercepts any message_type starting with "tenant_" and
        actually dispatches SMS/e-mail through the OneCore API, then rewrites
        the type to a failed_* variant when the call fails. In a test that
        means a live HTTP attempt AND a message_type that is not the one asked
        for.

        So: create with a benign type, then write() the real one. write() is not
        overridden on mail.message, and categorisation reads only the final
        message_type and subtype_id — so this is a faithful fixture.

        create() also reads values["message_type"] unguarded, so it must always
        be supplied.
        """
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.thread.id,
                "body": f"<p>{message_type}</p>",
                "message_type": "notification",
                "subtype_id": subtype.id if subtype else False,
            }
        )
        if message_type != "notification":
            message.write({"message_type": message_type})
        return message

    def test_notification_is_event(self):
        message = self._message("notification", self.note_subtype)
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_EVENT)

    def test_log_note_is_internal_note(self):
        message = self._message("comment", self.note_subtype)
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_INTERNAL_NOTE)

    def test_public_comment_is_communication(self):
        message = self._message("comment", self.comment_subtype)
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_COMMUNICATION)

    def test_tenant_sms_is_communication(self):
        message = self._message("tenant_sms", self.comment_subtype)
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_COMMUNICATION)

    def test_receipt_to_tenant_is_communication(self):
        """MIM-1960's kvittens carries the INTERNAL mail.mt_note subtype but is
        genuinely visible to the tenant on Mina sidor, so it belongs in
        Kommunikation. This is a regression lock on that decision: it passes
        only because the internal-note rule also requires message_type
        == 'comment'."""
        message = self._message("receipt_to_tenant", self.note_subtype)
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_COMMUNICATION)

    def test_message_without_subtype_is_communication(self):
        """Pins NULL handling. A message with no subtype at all must still land
        in exactly one bucket rather than falling through."""
        message = self._message("from_tenant")
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_COMMUNICATION)

    def test_every_message_type_is_classified(self):
        """Fails the build when a new message_type is added without a
        deliberate category. See the EXPECTED_CATEGORIES comment."""
        # get_values() is the documented accessor and returns the selection
        # AFTER selection_add merging, which is what we need here.
        live_types = set(
            self.env["mail.message"]._fields["message_type"].get_values(self.env)
        ) - {"user_notification"}
        self.assertEqual(
            live_types,
            set(EXPECTED_CATEGORIES),
            "A message_type was added or removed without updating "
            "EXPECTED_CATEGORIES. A new type that is neither 'comment' nor "
            "'notification' falls into Kommunikation by default — decide "
            "whether that is correct, then list it here.",
        )

    def test_expected_categories_match_the_rule_table(self):
        for message_type, expected in EXPECTED_CATEGORIES.items():
            subtype = (
                self.comment_subtype if message_type == "comment" else self.note_subtype
            )
            message = self._message(message_type, subtype)
            self.assertEqual(
                message.onecore_log_category,
                expected,
                f"{message_type} classified as "
                f"{message.onecore_log_category}, expected {expected}",
            )

    def test_compute_and_domain_agree(self):
        """The rule table has two consumers — the computed field and the search
        domain. This is the test that catches them drifting apart."""
        messages = (
            self._message("notification", self.note_subtype)
            + self._message("comment", self.note_subtype)
            + self._message("comment", self.comment_subtype)
            + self._message("tenant_sms", self.comment_subtype)
            + self._message("receipt_to_tenant", self.note_subtype)
            + self._message("from_tenant")
        )
        MailMessage = self.env["mail.message"]
        for category in (
            LOG_CATEGORY_EVENT,
            LOG_CATEGORY_INTERNAL_NOTE,
            LOG_CATEGORY_COMMUNICATION,
        ):
            domain = MailMessage._onecore_log_category_domain(category)
            by_domain = MailMessage.search(
                domain & Domain([("id", "in", messages.ids)])
            )
            by_compute = messages.filtered(lambda m: m.onecore_log_category == category)
            self.assertEqual(
                set(by_domain.ids),
                set(by_compute.ids),
                f"domain and compute disagree for {category}",
            )

    def test_categories_partition_all_messages(self):
        """The three filters must sum to Alla, with no overlap: every message
        visible under exactly one filter, none invisible under all three."""
        messages = self.env["mail.message"]
        for message_type in EXPECTED_CATEGORIES:
            subtype = (
                self.comment_subtype if message_type == "comment" else self.note_subtype
            )
            messages += self._message(message_type, subtype)
        messages += self._message("comment", self.note_subtype)  # intern notering
        messages += self._message("from_tenant")  # no subtype

        MailMessage = self.env["mail.message"]
        seen = []
        for category in (
            LOG_CATEGORY_EVENT,
            LOG_CATEGORY_INTERNAL_NOTE,
            LOG_CATEGORY_COMMUNICATION,
        ):
            domain = MailMessage._onecore_log_category_domain(category)
            seen += MailMessage.search(
                domain & Domain([("id", "in", messages.ids)])
            ).ids

        self.assertEqual(
            sorted(seen), sorted(messages.ids), "categories are not a partition"
        )
        self.assertEqual(len(seen), len(set(seen)), "a message matched two categories")

    def test_unknown_category_raises(self):
        with self.assertRaises(ValueError):
            self.env["mail.message"]._onecore_log_category_domain("nonsense")

    def test_category_is_serialized_to_the_store(self):
        """Gate 2 in the browser compares msg.onecore_log_category, so the field
        has to reach the OWL store.

        _to_store_defaults() needs a real Store.Target(): base mail_message.py
        calls target.is_internal(self.env) directly (not lazily, unlike the
        other target-dependent fields), so plain None raises AttributeError
        before onecore_log_category is ever appended. Store.Target() with no
        channel/subchannel is the "no target" case its own is_internal()
        docstring describes, so this stays a faithful check of "is the field
        present in the returned list", which is all this test claims to cover.
        """
        self.assertIn(
            "onecore_log_category",
            self.env["mail.message"]._to_store_defaults(Store.Target()),
        )
