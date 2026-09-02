import logging

from odoo import fields
from odoo.fields import Domain
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tools.discuss import Store

# EXPECTED_CATEGORIES lives next to the rule table it guards, in
# models/mail_message.py, because a developer adding a message_type is already
# editing that file and has no reason to open this one.
from ..models.mail_message import (
    EXPECTED_CATEGORIES,
    LOG_CATEGORY_COMMUNICATION,
    LOG_CATEGORY_EVENT,
    LOG_CATEGORY_INTERNAL_NOTE,
)

_logger = logging.getLogger(__name__)


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

    def _live_message_types(self):
        """The message_type selection as installed, minus user_notification.

        get_values() is the documented accessor and returns the selection AFTER
        selection_add merging, which is what we need here.
        """
        return set(
            self.env["mail.message"]._fields["message_type"].get_values(self.env)
        ) - {"user_notification"}

    def _live_expected_categories(self):
        """EXPECTED_CATEGORIES restricted to types this database actually has.

        `sms` and `snailmail` arrive through auto_install, not through the -i
        list, which differs between run_tests.sh and the CI workflow. Writing a
        message_type that is not in the live selection raises, so every test
        that iterates the map has to iterate this instead.
        """
        live = self._live_message_types()
        return {k: v for k, v in EXPECTED_CATEGORIES.items() if k in live}

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

    def test_comment_without_subtype_is_communication(self):
        """The one cell the matrix was missing, and the only case where the
        relational half of the rule decides on its own.

        Every other subtype-less case here uses a non-"comment" type, where
        `message_type == "comment"` short-circuits the internal-note rule (and,
        in the domain, satisfies the negation through the plain column). A
        subtype-less *comment* is the case that actually exercises
        `subtype_id.internal` against NULL. The domain half is covered by
        test_compute_and_domain_agree and test_categories_partition_all_messages,
        which both include this message.
        """
        message = self._message("comment")
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_COMMUNICATION)

    def test_every_message_type_is_classified(self):
        """Fails the build when a new message_type is added without a
        deliberate category. See the EXPECTED_CATEGORIES comment.

        One-directional on purpose. The guard that matters is "no live type is
        missing from the map"; asserting set equality would also fail when a
        type present in the map is not installed, and `sms`/`snailmail` arrive
        via auto_install rather than this repo's -i list, which differs between
        run_tests.sh and .github/workflows/test.yml. That direction is logged,
        not asserted, so the build only breaks for the reason this test exists.
        """
        live_types = self._live_message_types()
        unclassified = live_types - set(EXPECTED_CATEGORIES)
        self.assertFalse(
            unclassified,
            f"message_type(s) {sorted(unclassified)} are not in "
            "EXPECTED_CATEGORIES (onecore_mail_extension/models/"
            "mail_message.py). A new type that is neither 'comment' nor "
            "'notification' falls into Kommunikation by default — decide "
            "whether that is correct, then list it there.",
        )
        not_installed = set(EXPECTED_CATEGORIES) - live_types
        if not_installed:
            _logger.info(
                "EXPECTED_CATEGORIES lists message_type(s) that are not "
                "installed in this database, skipped: %s",
                sorted(not_installed),
            )

    def test_expected_categories_match_the_rule_table(self):
        for message_type, expected in self._live_expected_categories().items():
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
            # Subtype-less comment: the only case where the negated
            # subtype_id.internal condition decides the outcome on its own, so
            # this is what pins the domain's NULL-safety.
            + self._message("comment")
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
        for message_type in self._live_expected_categories():
            subtype = (
                self.comment_subtype if message_type == "comment" else self.note_subtype
            )
            messages += self._message(message_type, subtype)
        messages += self._message("comment", self.note_subtype)  # intern notering
        messages += self._message("from_tenant")  # no subtype
        messages += self._message("comment")  # comment, no subtype at all

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
        """The domain builder keeps raising, so a genuine programmer error in
        server code still surfaces loudly. Client input never reaches it — see
        test_sanitize_drops_unknown_category."""
        with self.assertRaises(ValueError):
            self.env["mail.message"]._onecore_log_category_domain("nonsense")

    def test_sanitize_drops_unknown_category(self):
        """onecore_log_category arrives from the browser through
        /onecore/mail/thread/messages, so a bogus value must not become a 500
        (plus a traceback in the log) via the ValueError above. Unknown values
        are dropped, which makes the fetch behave as Alla."""
        MailMessage = self.env["mail.message"]
        for bogus in ("nonsense", "EVENT", "event; drop table", 42):
            self.assertIsNone(
                MailMessage._onecore_sanitize_log_category(bogus),
                f"{bogus!r} should have been dropped",
            )

    def test_sanitize_keeps_known_categories(self):
        MailMessage = self.env["mail.message"]
        for category in (
            LOG_CATEGORY_EVENT,
            LOG_CATEGORY_INTERNAL_NOTE,
            LOG_CATEGORY_COMMUNICATION,
        ):
            self.assertEqual(
                MailMessage._onecore_sanitize_log_category(category), category
            )

    def test_sanitize_treats_empty_as_no_filter(self):
        """None / False / "" all mean Alla, and must not be logged as bogus."""
        MailMessage = self.env["mail.message"]
        for empty in (None, False, ""):
            self.assertIsNone(MailMessage._onecore_sanitize_log_category(empty))

    def test_message_fetch_with_bogus_category_is_unfiltered(self):
        """End-to-end on the client-facing path: a bogus category from the
        browser yields the unfiltered log rather than an error."""
        MailMessage = self.env["mail.message"]
        event_msg = self._message("notification", self.note_subtype)
        sms_msg = self._message("tenant_sms", self.comment_subtype)
        fetched = MailMessage._message_fetch(
            domain=None,
            thread=self.thread,
            onecore_log_category=MailMessage._onecore_sanitize_log_category("nonsense"),
        )["messages"]
        self.assertIn(event_msg.id, fetched.ids)
        self.assertIn(sms_msg.id, fetched.ids)

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

    def test_message_fetch_filters_by_category(self):
        self._message("notification", self.note_subtype)
        note = self._message("comment", self.note_subtype)
        sms = self._message("tenant_sms", self.comment_subtype)

        MailMessage = self.env["mail.message"]
        fetched = MailMessage._message_fetch(
            domain=None,
            thread=self.thread,
            onecore_log_category=LOG_CATEGORY_INTERNAL_NOTE,
        )["messages"]
        self.assertEqual(fetched.ids, note.ids)

        fetched = MailMessage._message_fetch(
            domain=None,
            thread=self.thread,
            onecore_log_category=LOG_CATEGORY_COMMUNICATION,
        )["messages"]
        self.assertEqual(fetched.ids, sms.ids)

    def test_message_fetch_without_category_is_unchanged(self):
        """Alla must stay byte-identical to today's behaviour."""
        MailMessage = self.env["mail.message"]
        event_msg = self._message("notification", self.note_subtype)
        internal_note_msg = self._message("comment", self.note_subtype)
        with_none = MailMessage._message_fetch(
            domain=None, thread=self.thread, onecore_log_category=None
        )["messages"]
        baseline = MailMessage._message_fetch(domain=None, thread=self.thread)[
            "messages"
        ]
        # Core of the test: passing onecore_log_category=None is identical to
        # not passing it at all.
        self.assertEqual(with_none.ids, baseline.ids)
        # The real risk is over-filtering, so also confirm both messages this
        # test just created are actually in the unfiltered fetch. (baseline
        # also carries a third message: res.partner.create() in setUpClass
        # auto-logs a "Contact created" message via mail.thread._message_log_batch
        # -- message_type "notification", subtype mail.mt_note, body
        # "Contact created" -- confirmed by inspecting it directly. It lands
        # in Händelse, not Intern notering, because _onecore_log_category_for
        # checks message_type before subtype. Expected, and not asserted on
        # here.)
        self.assertIn(event_msg.id, baseline.ids)
        self.assertIn(internal_note_msg.id, baseline.ids)

    def test_pagination_applies_after_filtering(self):
        """The reason this filter is server-side. With 40 events ahead of 5
        kommunikation, a client-side filter over a 30-message page would show
        zero. The server must return all 5."""
        for _index in range(40):
            self._message("notification", self.note_subtype)
        for _index in range(5):
            self._message("tenant_sms", self.comment_subtype)

        fetched = self.env["mail.message"]._message_fetch(
            domain=None,
            thread=self.thread,
            onecore_log_category=LOG_CATEGORY_COMMUNICATION,
            limit=30,
        )["messages"]
        self.assertEqual(len(fetched), 5)

    def test_pinned_fetch_ignores_category(self):
        """The 'Fästa noteringar' section stays unfiltered by construction."""
        note = self._message("comment", self.note_subtype)
        note.pinned_at = fields.Datetime.now()
        pinned = self.env["mail.message"]._fetch_pinned_messages(self.thread)
        self.assertEqual(pinned.ids, note.ids)
