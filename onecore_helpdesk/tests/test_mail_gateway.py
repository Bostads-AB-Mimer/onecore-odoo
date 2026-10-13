from odoo.tests import TransactionCase, tagged

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
        message = EMAIL_TEMPLATE.format(
            sender="Anna Andersson <anna.andersson@mimer.nu>",
            to=self.team_address,
            msg_id=msg_id,
            extra_headers=extra,
            subject=subject,
            body=body,
        )
        return self.env["mail.thread"].message_process(None, message)

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
            extra="In-Reply-To: <first@test.mimer.nu>\n"
            "References: <first@test.mimer.nu>\n",
        )

        self.assertEqual(reply_id, ticket_id)
        self.assertEqual(self.Ticket.search_count([]), tickets_before)
        ticket = self.Ticket.browse(ticket_id)
        self.assertIn(
            "<reply@test.mimer.nu>", ticket.message_ids.mapped("message_id")
        )
