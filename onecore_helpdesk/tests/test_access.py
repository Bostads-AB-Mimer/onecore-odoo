from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

EMPLOYEE = "base.group_user"
TEAM_HANDLER = "helpdesk_mgmt.group_helpdesk_user_team"
ALL_TICKETS_HANDLER = "helpdesk_mgmt.group_helpdesk_user"


def create_user(env, name, login, group_xmlid, password=None):
    vals = {
        "name": name,
        "login": login,
        "email": login,
        "group_ids": [(6, 0, [env.ref(group_xmlid).id])],
    }
    if password:
        vals["password"] = password
    return env["res.users"].create(vals)


def create_ticket(env, name, requester, team):
    return env["helpdesk.ticket"].create(
        {
            "name": name,
            "description": "Beskrivning",
            "partner_id": requester.id,
            "team_id": team.id,
        }
    )


@tagged("onecore", "post_install", "-at_install")
class TestItTicketAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Ticket = cls.env["helpdesk.ticket"]
        cls.team = cls.env.ref("onecore_helpdesk.team_it")
        other_team = cls.env["helpdesk.ticket.team"].create({"name": "Kommunikation"})

        cls.employee_a = create_user(
            cls.env, "Anställd A", "anstalld.a@test.mimer.nu", EMPLOYEE
        )
        cls.employee_b = create_user(
            cls.env, "Anställd B", "anstalld.b@test.mimer.nu", EMPLOYEE
        )
        cls.handler_1 = create_user(
            cls.env, "IT-handläggare 1", "it.handlaggare1@test.mimer.nu", TEAM_HANDLER
        )
        cls.handler_2 = create_user(
            cls.env, "IT-handläggare 2", "it.handlaggare2@test.mimer.nu", TEAM_HANDLER
        )
        cls.all_tickets_handler = create_user(
            cls.env,
            "Helpdesk-användare",
            "helpdesk.anvandare@test.mimer.nu",
            ALL_TICKETS_HANDLER,
        )
        cls.team.user_ids = [(4, cls.handler_1.id), (4, cls.handler_2.id)]

        cls.ticket = create_ticket(
            cls.env, "Skrivaren på plan 3", cls.employee_a.partner_id, cls.team
        )
        outside_requester = cls.env["res.partner"].create({"name": "Extern beställare"})
        cls.other_team_ticket = create_ticket(
            cls.env, "Pressmeddelande", outside_requester, other_team
        )
        cls.all_tickets = cls.ticket | cls.other_team_ticket

    def test_requester_sees_own_ticket(self):
        self.assertNotIn(self.employee_a.partner_id, self.ticket.message_partner_ids)

        self.ticket.with_user(self.employee_a).check_access("read")
        self.assertEqual(self.Ticket.with_user(self.employee_a).search([]), self.ticket)

    def test_another_employee_sees_nothing(self):
        self.assertFalse(self.Ticket.with_user(self.employee_b).search([]))
        with self.assertRaises(AccessError):
            self.ticket.with_user(self.employee_b).read(["name"])

    def test_follower_sees_the_ticket(self):
        self.ticket.message_subscribe(partner_ids=self.employee_b.partner_id.ids)

        self.ticket.with_user(self.employee_b).check_access("read")
        self.assertEqual(self.Ticket.with_user(self.employee_b).search([]), self.ticket)

    def test_employee_cannot_change_tickets_in_the_backend(self):
        with self.assertRaises(AccessError):
            self.ticket.with_user(self.employee_a).write({"name": "Ny rubrik"})
        with self.assertRaises(AccessError):
            self.Ticket.with_user(self.employee_a).create(
                {"name": "Ny skärm", "description": "Beskrivning"}
            )

    def test_team_handler_sees_the_team_tickets_only(self):
        visible = self.Ticket.with_user(self.handler_1).search(
            [("id", "in", self.all_tickets.ids)]
        )

        self.assertEqual(visible, self.ticket)

    def test_team_handler_can_take_over_a_colleagues_ticket(self):
        self.ticket.user_id = self.handler_1

        colleague_view = self.Ticket.with_user(self.handler_2).search(
            [("user_id", "=", self.handler_1.id)]
        )
        self.assertEqual(colleague_view, self.ticket)

        colleague_view.user_id = self.handler_2
        self.assertEqual(self.ticket.user_id, self.handler_2)

    def test_all_tickets_handler_sees_every_team(self):
        visible = self.Ticket.with_user(self.all_tickets_handler).search(
            [("id", "in", self.all_tickets.ids)]
        )

        self.assertEqual(visible, self.all_tickets)


@tagged("onecore", "post_install", "-at_install")
class TestItTicketPortalAccess(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        team = cls.env.ref("onecore_helpdesk.team_it")
        employee_a = create_user(
            cls.env,
            "Anställd A",
            "anstalld.a@test.mimer.nu",
            EMPLOYEE,
            password="anstalld-a-test",
        )
        employee_b = create_user(
            cls.env, "Anställd B", "anstalld.b@test.mimer.nu", EMPLOYEE
        )
        cls.own_ticket = create_ticket(
            cls.env, "Skrivaren på plan 3", employee_a.partner_id, team
        )
        cls.colleague_ticket = create_ticket(
            cls.env, "Ny dockningsstation", employee_b.partner_id, team
        )

    def setUp(self):
        super().setUp()
        self.authenticate("anstalld.a@test.mimer.nu", "anstalld-a-test")

    def test_my_tickets_lists_only_own_tickets(self):
        response = self.url_open("/my/tickets")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Skrivaren på plan 3", response.text)
        self.assertNotIn("Ny dockningsstation", response.text)

    def test_ticket_page_opens_only_for_own_ticket(self):
        response = self.url_open(f"/my/ticket/{self.own_ticket.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Skrivaren på plan 3", response.text)

        response = self.url_open(
            f"/my/ticket/{self.colleague_ticket.id}", allow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/my"))
