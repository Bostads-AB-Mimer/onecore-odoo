from odoo.tests import TransactionCase, tagged

from .test_mail_gateway import EMAIL_TEMPLATE

OCA_STAGE_XMLIDS = [
    "helpdesk_mgmt.helpdesk_ticket_stage_new",
    "helpdesk_mgmt.helpdesk_ticket_stage_in_progress",
    "helpdesk_mgmt.helpdesk_ticket_stage_awaiting",
    "helpdesk_mgmt.helpdesk_ticket_stage_done",
    "helpdesk_mgmt.helpdesk_ticket_stage_cancelled",
    "helpdesk_mgmt.helpdesk_ticket_stage_rejected",
]


@tagged("onecore", "post_install", "-at_install")
class TestItTeamConfig(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env.ref
        cls.team = ref("onecore_helpdesk.team_it")
        cls.stage_new = ref("onecore_helpdesk.stage_new")
        cls.stage_awaiting_user = ref("onecore_helpdesk.stage_awaiting_user")
        cls.stage_user_replied = ref("onecore_helpdesk.stage_user_replied")
        cls.stage_solved = ref("onecore_helpdesk.stage_solved")
        cls.stage_closed = ref("onecore_helpdesk.stage_closed")

        alias_domain = cls.env["mail.alias.domain"].create({"name": "test.mimer.nu"})
        cls.env.company.alias_domain_id = alias_domain
        cls.team.alias_name = "it-config-test"
        cls.team_address = "it-config-test@test.mimer.nu"

        cls.handler = cls.env["res.users"].create(
            {
                "name": "IT-handläggare",
                "login": "it.handlaggare@test.mimer.nu",
                "email": "it.handlaggare@test.mimer.nu",
                "group_ids": [
                    (6, 0, [ref("helpdesk_mgmt.group_helpdesk_user_team").id])
                ],
            }
        )
        cls.team.user_ids = [(4, cls.handler.id)]

    def _process(self, subject, msg_id, extra=""):
        message = EMAIL_TEMPLATE.format(
            sender="Anna Andersson <anna.andersson@mimer.nu>",
            to=self.team_address,
            msg_id=msg_id,
            extra_headers=extra,
            subject=subject,
            body="Skrivaren fungerar inte.",
        )
        return self.env["mail.thread"].message_process(None, message)

    def _ticket_from_mail(self):
        ticket_id = self._process("Skrivaren på plan 3", "<first@test.mimer.nu>")
        return self.env["helpdesk.ticket"].browse(ticket_id)

    def _reply(self, msg_id):
        self._process(
            "Re: Skrivaren på plan 3",
            msg_id,
            extra="In-Reply-To: <first@test.mimer.nu>\n"
            "References: <first@test.mimer.nu>\n",
        )

    def _p1_mails(self, ticket):
        return self.env["mail.mail"].search(
            [
                ("model", "=", "helpdesk.ticket"),
                ("res_id", "=", ticket.id),
                ("subject", "=like", "P1:%"),
            ]
        )

    def test_only_the_it_stages_are_offered(self):
        for xmlid in OCA_STAGE_XMLIDS:
            self.assertFalse(self.env.ref(xmlid).active, xmlid)
        self.assertEqual(
            self.team._get_applicable_stages().mapped("name"),
            [
                "Ny",
                "Pågår",
                "Väntar på användare",
                "Återkopplad",
                "Beställd",
                "Löst",
                "Stängt",
            ],
        )

    def test_team_has_the_it_categories(self):
        self.assertEqual(len(self.team.category_ids), 6)

    def test_new_ticket_from_mail_starts_in_ny(self):
        ticket = self._ticket_from_mail()

        self.assertEqual(ticket.team_id, self.team)
        self.assertEqual(ticket.stage_id, self.stage_new)

    def test_reply_on_awaiting_user_moves_to_user_replied(self):
        ticket = self._ticket_from_mail()
        ticket.stage_id = self.stage_awaiting_user

        self._reply("<reply-awaiting@test.mimer.nu>")

        self.assertEqual(ticket.stage_id, self.stage_user_replied)

    def test_reply_on_solved_reopens_as_user_replied(self):
        ticket = self._ticket_from_mail()
        ticket.stage_id = self.stage_solved

        self._reply("<reply-solved@test.mimer.nu>")

        self.assertEqual(ticket.stage_id, self.stage_user_replied)

    def test_reply_on_closed_does_not_reopen(self):
        ticket = self._ticket_from_mail()
        ticket.stage_id = self.stage_closed

        self._reply("<reply-closed@test.mimer.nu>")

        self.assertEqual(ticket.stage_id, self.stage_closed)

    def test_solved_tickets_close_after_two_inactive_days(self):
        self.assertTrue(self.team.close_inactive_tickets)
        self.assertEqual(self.team.ticket_stage_ids, self.stage_solved)
        self.assertEqual(self.team.inactive_tickets_day_limit_closing, 2)
        self.assertEqual(self.team.inactive_tickets_day_limit_warning, 0)
        self.assertFalse(self.team.close_inactive_mail_template_id)
        self.assertEqual(self.team.closing_ticket_stage, self.stage_closed)

    def test_p1_mails_the_team_members_once(self):
        requester = self.env["res.partner"].create(
            {"name": "Anna Andersson", "email": "anna.andersson@mimer.nu"}
        )
        ticket = self.env["helpdesk.ticket"].create(
            {
                "name": "Servern svarar inte",
                "description": "Ingen kommer åt filservern.",
                "team_id": self.team.id,
                "partner_id": requester.id,
                "priority": "1",
            }
        )
        self.assertFalse(self._p1_mails(ticket))

        ticket.priority = "3"

        mails = self._p1_mails(ticket)
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails.recipient_ids, self.handler.partner_id)
        self.assertFalse(mails.email_to)

        ticket.write({"description": "Fortfarande nere.", "priority": "3"})

        self.assertEqual(len(self._p1_mails(ticket)), 1)

    def test_ticket_created_as_p1_mails_the_team(self):
        ticket = self.env["helpdesk.ticket"].create(
            {
                "name": "Hela nätverket är nere",
                "description": "Inget fungerar.",
                "team_id": self.team.id,
                "priority": "3",
            }
        )

        self.assertEqual(len(self._p1_mails(ticket)), 1)
