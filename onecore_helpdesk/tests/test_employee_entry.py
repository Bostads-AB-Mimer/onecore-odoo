from lxml import html

from odoo.tests import HttpCase, TransactionCase, tagged

from .test_access import EMPLOYEE, TEAM_HANDLER, create_ticket, create_user


@tagged("onecore", "post_install", "-at_install")
class TestEmployeeHelpdeskMenu(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.entry = cls.env.ref("onecore_helpdesk.menu_employee_helpdesk")
        cls.admin_app = cls.env.ref("helpdesk_mgmt.helpdesk_ticket_main_menu")
        cls.employee = create_user(
            cls.env, "Anställd A", "anstalld.a@test.mimer.nu", EMPLOYEE
        )
        cls.handler = create_user(
            cls.env, "IT-handläggare 1", "it.handlaggare1@test.mimer.nu", TEAM_HANDLER
        )

    def _apps(self, user, lang="en_US"):
        menus = (
            self.env["ir.ui.menu"]
            .with_user(user)
            .with_context(lang=lang)
            .load_menus(False)
        )
        return [menus[menu_id] for menu_id in menus["root"]["children"]]

    def test_employee_sees_the_entry_but_not_the_admin_app(self):
        app_ids = [app["id"] for app in self._apps(self.employee)]

        self.assertIn(self.entry.id, app_ids)
        self.assertNotIn(self.admin_app.id, app_ids)

    def test_entry_is_not_the_app_employees_land_on(self):
        app_ids = [app["id"] for app in self._apps(self.employee)]

        self.assertNotEqual(app_ids[0], self.entry.id)

    def test_entry_opens_my_tickets_in_the_same_tab(self):
        action = self.entry.action

        self.assertEqual(action._name, "ir.actions.act_url")
        self.assertEqual(action.url, "/my/tickets")
        self.assertEqual(action.target, "self")

    def test_entry_has_an_icon(self):
        apps = {app["id"]: app for app in self._apps(self.employee)}

        self.assertTrue(apps[self.entry.id]["web_icon_data"])

    def test_handler_sees_both_apps_under_different_names_in_swedish(self):
        self.env["res.lang"]._activate_lang("sv_SE")
        # helpdesk_mgmt's Swedish name, as its translation file loads it
        self.admin_app.update_field_translations("name", {"sv_SE": "Helpdesk"})

        self.admin_app._set_name_in_all_languages("Helpdesk admin")

        apps = self._apps(self.handler, "sv_SE")
        names = {app["id"]: app["name"] for app in apps}
        self.assertEqual(names[self.entry.id], "Helpdesk")
        self.assertEqual(names[self.admin_app.id], "Helpdesk admin")

    def test_admin_app_is_renamed_on_install(self):
        self.assertEqual(
            self.admin_app.with_context(lang="en_US").name, "Helpdesk admin"
        )


@tagged("onecore", "post_install", "-at_install")
class TestEmployeeTicketPortalPages(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        team = cls.env.ref("onecore_helpdesk.team_it")
        cls.employee = create_user(
            cls.env,
            "Anställd A",
            "anstalld.a@test.mimer.nu",
            EMPLOYEE,
            password="anstalld-a-test",
        )
        create_ticket(cls.env, "Skrivaren på plan 3", cls.employee.partner_id, team)

    def setUp(self):
        super().setUp()
        self.authenticate("anstalld.a@test.mimer.nu", "anstalld-a-test")

    def _page(self, url):
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content)

    def _text(self, page, xpath):
        return [" ".join(node.text_content().split()) for node in page.xpath(xpath)]

    def _breadcrumb(self, page, xpath):
        return self._text(page, "//ol[contains(@class, 'breadcrumb')]" + xpath)

    def _new_ticket_buttons(self, page, within=""):
        return self._text(
            page,
            within
            + "//form[@action='/new/ticket']//button[@name='create_new_ticket']",
        )

    def test_my_home_card_names_helpdesk_tickets_with_a_new_ticket_button(self):
        page = self._page("/my")

        card = self._text(page, "//a[@href='/my/tickets']")
        self.assertEqual(len(card), 1)
        self.assertIn("Helpdeskärenden", card[0])
        self.assertIn("Följ och kommentera dina helpdeskärenden", card[0])
        self.assertEqual(page.text_content().count("Helpdeskärenden"), 1)
        self.assertEqual(self._new_ticket_buttons(page), ["Nytt ärende"])

    def test_my_tickets_has_a_swedish_heading_and_a_new_ticket_button(self):
        page = self._page("/my/tickets")

        self.assertEqual(self._breadcrumb(page, "/li[last()]"), ["Helpdeskärenden"])
        self.assertEqual(len(self._new_ticket_buttons(page)), 2)
        self.assertEqual(
            self._new_ticket_buttons(
                page,
                "//nav[contains(@class, 'o_portal_navbar')]"
                "/div[contains(@class, 'd-lg-none')]",
            ),
            ["Nytt ärende"],
        )
        self.assertEqual(
            self._new_ticket_buttons(
                page,
                "//div[contains(@class, 'navbar-collapse')]"
                "//div[contains(@class, 'd-none') and contains(@class, 'd-lg-block')]",
            ),
            ["Nytt ärende"],
        )

    def test_ticket_page_links_back_to_helpdesk_tickets(self):
        ticket = self.env["helpdesk.ticket"].search(
            [("partner_id", "=", self.employee.partner_id.id)]
        )
        page = self._page(f"/my/ticket/{ticket.id}")

        self.assertEqual(
            self._breadcrumb(page, "//a[starts-with(@href, '/my/tickets')]"),
            ["Helpdeskärenden"],
        )

    def test_my_tickets_columns_and_options_are_in_swedish(self):
        page = self._page("/my/tickets")

        headers = self._text(page, "//thead//th")
        for header in ("Nummer", "Status", "Skapad", "Senaste statusändring", "Stängd"):
            self.assertIn(header, headers)

        def option(href_part):
            return self._text(page, f"//a[contains(@href, '{href_part}')]")

        self.assertEqual(option("sortby=stage"), ["Status"])
        self.assertEqual(option("sortby=update"), ["Senaste statusändring"])
        self.assertEqual(option("groupby=stage"), ["Status"])
        self.assertEqual(self._text(page, "//a[@href='#all']"), ["Sök i alla"])

    def test_grouped_list_headers_are_in_swedish(self):
        by_stage = self._page("/my/tickets?groupby=stage")
        by_category = self._page("/my/tickets?groupby=category")

        self.assertEqual(
            self._text(by_stage, "//th[@name='th_groupby_stage']/em"),
            ["Ärenden med status:"],
        )
        self.assertEqual(
            self._text(by_category, "//th[@name='th_groupby_category']/em"),
            ["Ärenden i kategori:"],
        )
