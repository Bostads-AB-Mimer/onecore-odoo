from markupsafe import Markup

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import email_normalize

from odoo.addons.mail.tests.common import MailCase

from .test_access import EMPLOYEE, TEAM_HANDLER, create_user

EMAIL_TEMPLATE = """Return-Path: <{sender}>
To: {to}
From: {sender}
Message-ID: {msg_id}
{extra_headers}Date: Tue, 13 Oct 2026 10:00:00 +0200
MIME-Version: 1.0
Subject: {subject}
Content-Type: text/plain; charset=UTF-8

{body}
"""

SENDER = "Anna Andersson <anna.andersson@mimer.nu>"
HANDLER_PASSWORD = "it-handlaggare-test"


def process_mail(
    env, to, subject, msg_id, sender=SENDER, body="Skrivaren fungerar inte.", extra=""
):
    """Feed one incoming mail to the gateway. ``env`` decides who runs it:
    the superuser, as the fetchmail cron does, or the user who clicked
    "Fetch now" on the incoming mail server."""
    message = EMAIL_TEMPLATE.format(
        sender=sender,
        to=to,
        msg_id=msg_id,
        extra_headers=extra,
        subject=subject,
        body=body,
    )
    return env["mail.thread"].message_process(None, message)


def reply_headers(message_id):
    return f"In-Reply-To: {message_id}\nReferences: {message_id}\n"


def send_message_as(user, ticket, body, suggested_recipients=True):
    """Post on the ticket the way the chatter does for ``user``.

    Mirrors the client and the /mail/message/post route: the backend's "Send
    message" sends every suggested recipient as an email address, the route
    turns the addresses into partners (creating a missing one only for a user
    with Contact Creation), keeps the ones the user may read and posts in sudo
    once the user's access to the ticket is checked. The portal chatter loads
    no suggested recipients: pass ``suggested_recipients=False`` for it.
    TestItAnswerOverChatterRoutes runs the same answer through the real
    routes.
    """
    Ticket = ticket.env["helpdesk.ticket"].with_user(user)
    ticket_su = Ticket.browse(ticket.id).sudo()
    operation = ticket_su._mail_get_operation_for_mail_message_operation("create")[
        ticket_su
    ]
    thread = Ticket._get_thread_with_access(ticket.id, mode=operation)
    if not thread:
        raise AccessError(f"{user.login} may not post on ticket {ticket.id}")
    values = {
        "body": Markup("<p>%s</p>") % body,
        "message_type": "comment",
        "subtype_xmlid": "mail.mt_comment",
        "email_add_signature": True,
    }
    if suggested_recipients:
        suggested = thread._message_get_suggested_recipients(
            reply_discussion=True, no_create=True
        )
        emails = [recipient["email"] for recipient in suggested]
        if not all(emails):
            raise ValueError("The composer does not send to a recipient without email")
        if emails:
            partners = thread._partner_find_from_emails_single(
                emails, no_create=not user.has_group("base.group_partner_manager")
            )
            values["partner_ids"] = partners.filtered(
                lambda partner: partner.has_access("read")
            ).ids
    if not Ticket._get_thread_with_access(ticket.id, mode="write"):
        thread = thread.with_context(
            mail_post_autofollow_author_skip=True, mail_post_autofollow=False
        )
    return thread.sudo().message_post(**values)


@tagged("onecore", "post_install", "-at_install")
class TestHelpdeskMailGateway(TransactionCase):
    """Incoming mail must become IT tickets and replies must land on the same
    ticket, with all onecore modules installed (onecore_mail_extension
    overrides mail.message.create for every model)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        alias_domain = cls.env["mail.alias.domain"].create({"name": "test.mimer.nu"})
        cls.env.company.alias_domain_id = alias_domain
        cls.team = cls.env["helpdesk.ticket.team"].create(
            {"name": "IT", "alias_name": "it-test"}
        )
        cls.team_address = "it-test@test.mimer.nu"
        cls.Ticket = cls.env["helpdesk.ticket"]

    def _process(self, subject, msg_id, body="Skrivaren fungerar inte.", extra=""):
        return process_mail(
            self.env, self.team_address, subject, msg_id, body=body, extra=extra
        )

    def test_incoming_mail_creates_ticket_in_alias_team(self):
        ticket_id = self._process("Skrivaren på plan 3", "<first@test.mimer.nu>")

        ticket = self.Ticket.browse(ticket_id)
        self.assertEqual(ticket._name, "helpdesk.ticket")
        self.assertEqual(ticket.team_id, self.team)
        self.assertEqual(ticket.name, "Skrivaren på plan 3")
        self.assertIn("anna.andersson@mimer.nu", ticket.partner_email)

    def test_reply_lands_on_the_same_ticket(self):
        ticket_id = self._process("Skrivaren på plan 3", "<first@test.mimer.nu>")
        tickets_before = self.Ticket.search_count([])

        reply_id = self._process(
            "Re: Skrivaren på plan 3",
            "<reply@test.mimer.nu>",
            body="Nu fungerar den igen, tack!",
            extra=reply_headers("<first@test.mimer.nu>"),
        )

        self.assertEqual(reply_id, ticket_id)
        self.assertEqual(self.Ticket.search_count([]), tickets_before)
        ticket = self.Ticket.browse(ticket_id)
        self.assertIn(
            "<reply@test.mimer.nu>", ticket.message_ids.mapped("message_id")
        )


@tagged("onecore", "post_install", "-at_install")
class TestItMailRoundTrip(MailCase):
    """Mail in and out on the real IT team, for a known contact and for an
    employee notified by email: a mail to the team's alias becomes a ticket,
    the handler's "Send message" reaches the requester with the alias as
    Reply-To, and the requester's reply to that mail comes back to the same
    ticket."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        alias_domain = cls.env["mail.alias.domain"].create({"name": "test.mimer.nu"})
        cls.env.company.alias_domain_id = alias_domain
        cls.team = cls.env.ref("onecore_helpdesk.team_it")
        cls.team.alias_name = "it-roundtrip-test"
        cls.team_address = "it-roundtrip-test@test.mimer.nu"
        cls.Ticket = cls.env["helpdesk.ticket"]
        cls.handler = create_user(
            cls.env, "IT-handläggare", "it.handlaggare@test.mimer.nu", TEAM_HANDLER
        )
        cls.team.user_ids = [(4, cls.handler.id)]

    def _ticket_from_mail(self, sender):
        ticket_id = process_mail(
            self.env,
            self.team_address,
            "Skrivaren på plan 3",
            "<first@test.mimer.nu>",
            sender=sender,
        )
        return self.Ticket.browse(ticket_id)

    def _answer(self, ticket):
        """The handler's "Send message": the posted answer and the mails that
        left Odoo because of it."""
        with self.mock_mail_gateway():
            answer = send_message_as(
                self.handler, ticket, "Har du provat att starta om skrivaren?"
            )
        return answer, self._mails

    def _assert_round_trip(self, sender):
        requester_address = email_normalize(sender)
        ticket = self._ticket_from_mail(sender)
        self.assertEqual(ticket.team_id, self.team)
        self.assertEqual(email_normalize(ticket.partner_email), requester_address)

        answer, mails = self._answer(ticket)

        self.assertEqual(len(mails), 1)
        mail = mails[0]
        self.assertEqual(
            [email_normalize(address) for address in mail["email_to"]],
            [requester_address],
        )
        self.assertEqual(email_normalize(mail["reply_to"]), self.team_address)
        self.assertEqual(mail["message_id"], answer.message_id)

        tickets_before = self.Ticket.search_count([])
        reply_id = process_mail(
            self.env,
            self.team_address,
            "Re: Skrivaren på plan 3",
            "<reply@test.mimer.nu>",
            sender=sender,
            body="Ja, men den skriver fortfarande inte ut.",
            extra=reply_headers(mail["message_id"]),
        )

        self.assertEqual(reply_id, ticket.id)
        self.assertEqual(self.Ticket.search_count([]), tickets_before)
        self.assertIn(
            "<reply@test.mimer.nu>", ticket.message_ids.mapped("message_id")
        )
        return ticket

    def test_round_trip_with_a_known_contact(self):
        contact = self.env["res.partner"].create(
            {"name": "Anna Andersson", "email": "anna.andersson@mimer.nu"}
        )
        self.assertFalse(contact.user_ids)

        ticket = self._assert_round_trip(SENDER)

        self.assertEqual(ticket.partner_id, contact)

    def test_round_trip_with_an_employee_notified_by_email(self):
        employee = create_user(
            self.env, "Anställd A", "anstalld.a@test.mimer.nu", EMPLOYEE
        )
        employee.notification_type = "email"

        ticket = self._assert_round_trip("Anställd A <anstalld.a@test.mimer.nu>")

        self.assertEqual(ticket.partner_id, employee.partner_id)


@tagged("onecore", "post_install", "-at_install")
class TestItAnswerOverChatterRoutes(HttpCase, MailCase):
    """The handler's answer through the routes the backend chatter calls,
    /mail/data for the suggested recipients and /mail/message/post for the
    post: the same answer that ``send_message_as`` mirrors, for a known
    contact."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        alias_domain = cls.env["mail.alias.domain"].create({"name": "test.mimer.nu"})
        cls.env.company.alias_domain_id = alias_domain
        cls.team = cls.env.ref("onecore_helpdesk.team_it")
        cls.team.alias_name = "it-routes-test"
        cls.team_address = "it-routes-test@test.mimer.nu"
        cls.handler = create_user(
            cls.env,
            "IT-handläggare",
            "it.handlaggare@test.mimer.nu",
            TEAM_HANDLER,
            password=HANDLER_PASSWORD,
        )
        cls.team.user_ids = [(4, cls.handler.id)]

    def _suggested_recipients(self, ticket):
        data = self.make_jsonrpc_request(
            "/mail/data",
            {
                "fetch_params": [
                    [
                        "mail.thread",
                        {
                            "thread_model": "helpdesk.ticket",
                            "thread_id": ticket.id,
                            "request_list": ["suggestedRecipients"],
                        },
                    ]
                ]
            },
        )
        thread = next(t for t in data["mail.thread"] if t["id"] == ticket.id)
        return thread["suggestedRecipients"]

    def test_answer_reaches_a_known_contact_and_the_reply_comes_back(self):
        self.env["res.partner"].create(
            {"name": "Anna Andersson", "email": "anna.andersson@mimer.nu"}
        )
        ticket = self.env["helpdesk.ticket"].browse(
            process_mail(
                self.env,
                self.team_address,
                "Skrivaren på plan 3",
                "<first@test.mimer.nu>",
            )
        )
        self.authenticate(self.handler.login, HANDLER_PASSWORD)

        suggested = self._suggested_recipients(ticket)
        with self.mock_mail_gateway():
            posted = self.make_jsonrpc_request(
                "/mail/message/post",
                {
                    "thread_model": "helpdesk.ticket",
                    "thread_id": ticket.id,
                    "post_data": {
                        "body": "<p>Har du provat att starta om skrivaren?</p>",
                        "email_add_signature": True,
                        "message_type": "comment",
                        "subtype_xmlid": "mail.mt_comment",
                        "partner_emails": [r["email"] for r in suggested],
                    },
                },
            )
        mails = self._mails

        self.assertEqual(
            [recipient["email"] for recipient in suggested],
            ["anna.andersson@mimer.nu"],
        )
        self.assertEqual(len(mails), 1)
        self.assertEqual(
            [email_normalize(address) for address in mails[0]["email_to"]],
            ["anna.andersson@mimer.nu"],
        )
        self.assertEqual(email_normalize(mails[0]["reply_to"]), self.team_address)
        answer = self.env["mail.message"].browse(posted["message_id"])
        self.assertEqual(answer.author_id, self.handler.partner_id)
        self.assertEqual(mails[0]["message_id"], answer.message_id)

        tickets_before = self.env["helpdesk.ticket"].search_count([])
        reply_id = process_mail(
            self.env,
            self.team_address,
            "Re: Skrivaren på plan 3",
            "<reply@test.mimer.nu>",
            body="Ja, men den skriver fortfarande inte ut.",
            extra=reply_headers(mails[0]["message_id"]),
        )

        self.assertEqual(reply_id, ticket.id)
        self.assertEqual(self.env["helpdesk.ticket"].search_count([]), tickets_before)
        self.assertIn("<reply@test.mimer.nu>", ticket.message_ids.mapped("message_id"))
