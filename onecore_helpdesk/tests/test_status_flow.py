from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCase

from .test_access import EMPLOYEE, TEAM_HANDLER, create_ticket, create_user
from .test_mail_gateway import process_mail, reply_headers, send_message_as


@tagged("onecore", "post_install", "-at_install")
class TestItStatusFlow(MailCase):
    """The status flow of the IT team: Löst closes by itself after the
    inactivity limit, the requester's own post reopens a waiting or solved
    ticket as Återkopplad, and Stängt stays closed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env.ref
        cls.team = ref("onecore_helpdesk.team_it")
        cls.stage_in_progress = ref("onecore_helpdesk.stage_in_progress")
        cls.stage_awaiting_user = ref("onecore_helpdesk.stage_awaiting_user")
        cls.stage_user_replied = ref("onecore_helpdesk.stage_user_replied")
        cls.stage_solved = ref("onecore_helpdesk.stage_solved")
        cls.stage_closed = ref("onecore_helpdesk.stage_closed")

        alias_domain = cls.env["mail.alias.domain"].create({"name": "test.mimer.nu"})
        cls.env.company.alias_domain_id = alias_domain
        cls.team.alias_name = "it-status-test"
        cls.team_address = "it-status-test@test.mimer.nu"

        cls.requester = create_user(
            cls.env, "Anställd A", "anstalld.a@test.mimer.nu", EMPLOYEE
        )
        cls.requester.notification_type = "email"
        cls.colleague = create_user(
            cls.env, "Anställd B", "anstalld.b@test.mimer.nu", EMPLOYEE
        )
        cls.handler = create_user(
            cls.env, "IT-handläggare", "it.handlaggare@test.mimer.nu", TEAM_HANDLER
        )
        cls.team.user_ids = [(4, cls.handler.id)]

    def _ticket(self, stage, days_in_stage=0, requester=None):
        ticket = create_ticket(
            self.env,
            "Skrivaren på plan 3",
            requester or self.requester.partner_id,
            self.team,
        )
        ticket.stage_id = stage
        if days_in_stage:
            ticket.last_stage_update = fields.Datetime.now() - timedelta(
                days=days_in_stage
            )
        return ticket

    def _run_auto_close(self):
        """What the "Close Inactive Tickets" cron runs."""
        self.env["helpdesk.ticket.team"].close_team_inactive_tickets()

    def _mail_from_requester(self, ticket, msg_id, gateway_env=None):
        """A mail from the requester, an employee with an Odoo user, that
        answers the ticket's first message."""
        first_message = ticket.message_ids.sorted("id")[:1]
        return process_mail(
            gateway_env or self.env,
            self.team_address,
            "Re: Skrivaren på plan 3",
            msg_id,
            sender="Anställd A <anstalld.a@test.mimer.nu>",
            body="Den fungerar fortfarande inte.",
            extra=reply_headers(first_message.message_id),
        )

    # Löst -> Stängt

    def test_solved_ticket_closes_after_the_inactivity_limit(self):
        ticket = self._ticket(self.stage_solved, days_in_stage=3)
        self.assertFalse(ticket.closed_date)

        self._run_auto_close()

        self.assertEqual(ticket.stage_id, self.stage_closed)
        self.assertTrue(ticket.closed_date)

    def test_solved_ticket_within_the_limit_stays_solved(self):
        ticket = self._ticket(self.stage_solved, days_in_stage=1)

        self._run_auto_close()

        self.assertEqual(ticket.stage_id, self.stage_solved)
        self.assertFalse(ticket.closed_date)

    def test_inactive_ticket_in_progress_is_not_closed(self):
        ticket = self._ticket(self.stage_in_progress, days_in_stage=3)

        self._run_auto_close()

        self.assertEqual(ticket.stage_id, self.stage_in_progress)
        self.assertFalse(ticket.closed_date)

    def test_auto_close_sends_a_following_contact_nothing(self):
        contact = self.env["res.partner"].create(
            {"name": "Anna Andersson", "email": "anna.andersson@mimer.nu"}
        )
        ticket = self._ticket(self.stage_solved, days_in_stage=3, requester=contact)
        ticket.message_subscribe(partner_ids=contact.ids)
        self.flush_tracking()
        messages_before = ticket.message_ids

        with self.mock_mail_gateway():
            self._run_auto_close()
            self.flush_tracking()

        self.assertEqual(ticket.stage_id, self.stage_closed)
        closing_messages = ticket.message_ids - messages_before
        self.assertTrue(closing_messages)
        self.assertFalse(self._mails)
        self.assertFalse(self._new_mails)
        self.assertFalse(
            self.env["mail.notification"].search(
                [("mail_message_id", "in", closing_messages.ids)]
            )
        )

    # the requester's own post -> Återkopplad

    def test_requester_post_on_awaiting_user_moves_to_user_replied(self):
        for from_backend in (True, False):
            with self.subTest(from_backend=from_backend):
                ticket = self._ticket(self.stage_awaiting_user)

                send_message_as(
                    self.requester,
                    ticket,
                    "Jag har startat om den.",
                    suggested_recipients=from_backend,
                )

                self.assertEqual(ticket.stage_id, self.stage_user_replied)

    def test_requester_post_on_solved_reopens_as_user_replied(self):
        for from_backend in (True, False):
            with self.subTest(from_backend=from_backend):
                ticket = self._ticket(self.stage_solved)

                send_message_as(
                    self.requester,
                    ticket,
                    "Felet är tillbaka.",
                    suggested_recipients=from_backend,
                )

                self.assertEqual(ticket.stage_id, self.stage_user_replied)

    def test_mail_from_a_requester_with_a_user_moves_to_user_replied_whoever_fetches_it(self):
        fetchers = {
            "cron": self.env,
            # "Fetch now" on the incoming mail server: the clicking user, in sudo
            "fetch now": self.env(user=self.env.ref("base.user_admin"), su=True),
        }
        for fetcher, gateway_env in fetchers.items():
            with self.subTest(fetcher=fetcher):
                ticket = self._ticket(self.stage_awaiting_user)

                thread_id = self._mail_from_requester(
                    ticket, f"<reply-{ticket.id}@test.mimer.nu>", gateway_env
                )

                self.assertEqual(thread_id, ticket.id)
                self.assertEqual(ticket.stage_id, self.stage_user_replied)

    def test_post_by_someone_else_keeps_the_stage(self):
        ticket = self._ticket(self.stage_awaiting_user)
        ticket.message_subscribe(partner_ids=self.colleague.partner_id.ids)

        handler_post = send_message_as(self.handler, ticket, "Har du hunnit prova?")
        colleague_post = send_message_as(
            self.colleague, ticket, "Jag har samma fel.", suggested_recipients=False
        )

        self.assertEqual(ticket.stage_id, self.stage_awaiting_user)
        self.assertIn(handler_post, ticket.message_ids)
        self.assertIn(colleague_post, ticket.message_ids)

    # Stängt stays closed

    def test_requester_post_on_closed_is_stored_and_keeps_the_stage(self):
        ticket = self._ticket(self.stage_closed)
        closed_date = ticket.closed_date
        self.assertTrue(closed_date)

        post = send_message_as(
            self.requester, ticket, "Felet är tillbaka.", suggested_recipients=False
        )

        self.assertEqual(ticket.stage_id, self.stage_closed)
        self.assertEqual(ticket.closed_date, closed_date)
        self.assertIn(post, ticket.message_ids)
        self.assertEqual(post.author_id, self.requester.partner_id)

    def test_requester_mail_on_closed_is_stored_and_keeps_the_stage(self):
        ticket = self._ticket(self.stage_closed)
        tickets_before = self.env["helpdesk.ticket"].search_count([])

        thread_id = self._mail_from_requester(ticket, "<reply-closed@test.mimer.nu>")

        self.assertEqual(thread_id, ticket.id)
        self.assertEqual(self.env["helpdesk.ticket"].search_count([]), tickets_before)
        self.assertEqual(ticket.stage_id, self.stage_closed)
        reply = ticket.message_ids.filtered(
            lambda message: message.message_id == "<reply-closed@test.mimer.nu>"
        )
        self.assertEqual(len(reply), 1)
        self.assertEqual(reply.author_id, self.requester.partner_id)
        self.assertIn("Den fungerar fortfarande inte.", reply.body)
