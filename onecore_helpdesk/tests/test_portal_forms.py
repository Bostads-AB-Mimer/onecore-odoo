from odoo import http
from odoo.tests import tagged

from odoo.addons.base.tests.common import DISABLED_MAIL_CONTEXT, HttpCaseWithUserPortal


@tagged("onecore", "post_install", "-at_install")
class TestPortalTicketForms(HttpCaseWithUserPortal):
    """Requesters create tickets in the portal (/new/ticket) with the
    category's form, its questions and the category's add-on form, under the
    same rules as in the backend, and see their answers on the ticket page."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, **DISABLED_MAIL_CONTEXT))
        ref = cls.env.ref
        cls.Ticket = cls.env["helpdesk.ticket"]
        cls.team = ref("onecore_helpdesk.team_it")
        cls.category_fault = ref("onecore_helpdesk.category_it_fault")
        cls.category_other = ref("onecore_helpdesk.category_it_other")
        cls.category_equipment = ref("onecore_helpdesk.category_equipment_order")
        cls.form_fault = ref("onecore_helpdesk.form_it_fault")
        cls.addon_impact = ref("onecore_helpdesk.form_impact_addon")
        cls.form_typed = cls.env["helpdesk.ticket.form"].create(
            {
                "name": "Beställning med alla frågetyper",
                "category_id": cls.category_equipment.id,
                "ticket_properties": [
                    {"name": "quantity", "string": "Antal", "type": "integer", "required": True},
                    {"name": "budget", "string": "Budget", "type": "float"},
                    {"name": "urgent", "string": "Brådskande", "type": "boolean"},
                    {"name": "needed_by", "string": "Behövs senast", "type": "date"},
                    {"name": "install_at", "string": "Installation", "type": "datetime"},
                    {"name": "notes", "string": "Övrigt", "type": "text"},
                    {
                        "name": "accessories",
                        "string": "Tillbehör",
                        "type": "tags",
                        "tags": [["mouse", "Mus", 1], ["dock", "Docka", 2]],
                    },
                ],
            }
        )
        cls.form_hidden = cls.env["helpdesk.ticket.form"].create(
            {
                "name": "Internt felformulär",
                "category_id": cls.category_fault.id,
                "show_in_portal": False,
            }
        )
        # the portal must offer categories even when the OCA setting is off
        cls.env.ref("base.main_company").helpdesk_mgmt_portal_select_category = False
        cls.user_portal.tz = "Europe/Stockholm"

    def setUp(self):
        super().setUp()
        self.authenticate("portal", "portal")

    # the Påverkan add-on of the IT fault category, answered
    ADDON = {
        "addon_question_affected_scope": "me",
        "addon_question_impact": "limited",
    }

    def _post(self, **values):
        data = {
            "csrf_token": http.Request.csrf_token(self),
            "subject": "Skrivaren på plan 3",
            "description": "Skrivaren fungerar inte",
        }
        data.update(values)
        return self.url_open("/submitted/ticket", data=data, allow_redirects=False)

    def _submitted_ticket(self):
        return self.Ticket.search(
            [("partner_id", "=", self.partner_portal.id), ("name", "=", "Skrivaren på plan 3")]
        )

    def _answers(self, ticket, field_name="properties"):
        return {
            prop["name"]: prop.get("value")
            for prop in ticket.read([field_name])[0][field_name]
        }

    def assertRejected(self, response, message):
        self.assertEqual(response.status_code, 200)
        self.assertIn(message, response.text)
        self.assertFalse(self._submitted_ticket())

    # The page --------------------------------------------------------------

    def test_page_offers_categories_forms_and_both_question_blocks(self):
        response = self.url_open("/new/ticket")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="category"', response.text)
        self.assertIn('name="form"', response.text)
        self.assertIn(f'data-category-id="{self.category_fault.id}"', response.text)
        self.assertIn("Felanmälan IT", response.text)
        # the form's own questions
        for question in ("port_replicator", "program"):
            self.assertIn(f'name="question_{question}"', response.text)
        # the add-on, with its title and intro
        for question in ("affected_scope", "impact"):
            self.assertIn(f'name="addon_question_{question}"', response.text)
        self.assertIn("Påverkan", response.text)
        self.assertIn("Här nedan väljer du vilken påverkan", response.text)
        self.assertIn("Vilka påverkas?", response.text)
        self.assertIn("Bara jag", response.text)

    def test_page_leaves_out_forms_hidden_from_the_portal_but_not_addons(self):
        self.addon_impact.show_in_portal = False

        response = self.url_open("/new/ticket")

        self.assertNotIn("Internt felformulär", response.text)
        self.assertIn('name="addon_question_impact"', response.text)

    def test_page_lists_addons_nowhere_in_the_form_select(self):
        response = self.url_open("/new/ticket")
        self.assertNotRegex(response.text, rf'<option[^>]*value="{self.addon_impact.id}"')

    def test_page_keeps_entered_values_after_a_rejected_submit(self):
        response = self._post(
            category=self.category_fault.id,
            form=self.form_fault.id,
            question_port_replicator="4137-12",
            addon_question_affected_scope="department",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="Skrivaren på plan 3"', response.text)
        self.assertIn("Skrivaren fungerar inte", response.text)
        self.assertIn('value="4137-12"', response.text)
        self.assertRegex(response.text, r'value="department"[^>]*selected')
        self.assertRegex(response.text, rf'value="{self.form_fault.id}"[^>]*selected')

    # Submitting ------------------------------------------------------------

    def test_submit_stores_both_blocks_and_routes_to_the_team(self):
        response = self._post(
            category=self.category_fault.id,
            form=self.form_fault.id,
            question_program="teams",
            **self.ADDON,
        )
        ticket = self._submitted_ticket()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(f"/my/ticket/{ticket.id}"))
        self.assertEqual(ticket.category_id, self.category_fault)
        self.assertEqual(ticket.form_id, self.form_fault)
        self.assertEqual(ticket.addon_form_id, self.addon_impact)
        self.assertEqual(ticket.team_id, self.team)
        self.assertEqual(ticket.partner_id, self.partner_portal)
        answers = self._answers(ticket)
        self.assertEqual(answers["program"], "teams")
        self.assertFalse(answers["port_replicator"])
        addon = self._answers(ticket, "addon_properties")
        self.assertEqual(addon["affected_scope"], "me")
        self.assertEqual(addon["impact"], "limited")

    def test_submit_without_category_is_rejected(self):
        response = self._post(form=self.form_fault.id)
        self.assertRejected(response, "Välj en kategori")

    def test_submit_without_form_is_rejected_when_the_category_has_forms(self):
        response = self._post(category=self.category_fault.id, **self.ADDON)
        self.assertRejected(response, "kräver att du väljer ett formulär")

    def test_submit_without_required_addon_answer_is_rejected(self):
        response = self._post(
            category=self.category_fault.id,
            form=self.form_fault.id,
            addon_question_affected_scope="me",
        )
        self.assertRejected(response, "Besvara de obligatoriska frågorna")
        self.assertIn("Hur drabbas du/ni?", response.text)

    def test_submit_with_a_form_of_another_category_is_rejected(self):
        response = self._post(category=self.category_other.id, form=self.form_fault.id)
        self.assertRejected(response, "Formuläret kan inte användas")

    def test_submit_with_an_addon_as_form_is_rejected(self):
        response = self._post(
            category=self.category_fault.id, form=self.addon_impact.id, **self.ADDON
        )
        self.assertRejected(response, "Formuläret kan inte användas")

    def test_submit_with_a_form_hidden_from_the_portal_is_rejected(self):
        response = self._post(
            category=self.category_fault.id, form=self.form_hidden.id, **self.ADDON
        )
        self.assertRejected(response, "Formuläret kan inte användas")

    def test_submit_to_a_category_without_forms_or_addon(self):
        response = self._post(category=self.category_other.id)
        ticket = self._submitted_ticket()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ticket.category_id, self.category_other)
        self.assertFalse(ticket.form_id)
        self.assertFalse(ticket.addon_form_id)
        self.assertEqual(ticket.team_id, self.team)
        self.assertFalse(ticket.addon_properties)

    def test_submit_parses_every_question_type(self):
        response = self._post(
            category=self.category_equipment.id,
            form=self.form_typed.id,
            question_quantity="3",
            question_budget="12,5",
            question_urgent="1",
            question_needed_by="2026-11-01",
            question_install_at="2026-11-02T09:30",
            question_notes="  Två skärmar  ",
            question_accessories=["mouse", "dock"],
        )
        self.assertEqual(response.status_code, 302)
        answers = self._answers(self._submitted_ticket())
        self.assertEqual(answers["quantity"], 3)
        self.assertEqual(answers["budget"], 12.5)
        self.assertIs(answers["urgent"], True)
        self.assertEqual(answers["needed_by"], "2026-11-01")
        # Europe/Stockholm is UTC+1 in November
        self.assertEqual(answers["install_at"], "2026-11-02 08:30:00")
        self.assertEqual(answers["notes"], "Två skärmar")
        self.assertEqual(answers["accessories"], ["mouse", "dock"])

    def test_submit_leaves_optional_questions_unanswered(self):
        self._post(
            category=self.category_equipment.id,
            form=self.form_typed.id,
            question_quantity="1",
        )
        answers = self._answers(self._submitted_ticket())
        self.assertEqual(answers["quantity"], 1)
        self.assertIs(answers["urgent"], False)
        for name in ("budget", "needed_by", "install_at", "notes", "accessories"):
            self.assertFalse(answers[name], name)

    def test_submit_with_a_bad_number_is_rejected(self):
        response = self._post(
            category=self.category_equipment.id,
            form=self.form_typed.id,
            question_quantity="tre",
        )
        self.assertRejected(response, "Antal måste vara ett heltal")

    def test_submit_ignores_answers_outside_the_definition(self):
        self._post(
            category=self.category_equipment.id,
            form=self.form_typed.id,
            question_quantity="2",
            question_accessories=["mouse", "keyboard"],
            question_bogus="x",
            addon_question_impact="limited",
        )
        ticket = self._submitted_ticket()
        answers = self._answers(ticket)
        self.assertEqual(answers["accessories"], ["mouse"])
        self.assertNotIn("bogus", answers)
        self.assertFalse(ticket.addon_properties)

    # The ticket page -------------------------------------------------------

    def test_ticket_page_shows_form_and_answers_of_both_blocks(self):
        ticket = self.Ticket.create(
            {
                "name": "Teams startar inte",
                "description": "<p>Snurrar bara.</p>",
                "team_id": self.team.id,
                "partner_id": self.partner_portal.id,
                "category_id": self.category_fault.id,
                "form_id": self.form_fault.id,
                "properties": {"program": "teams"},
                "addon_properties": {"affected_scope": "department", "impact": "cannot_work"},
            }
        )
        response = self.url_open(f"/my/ticket/{ticket.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Felanmälan IT", response.text)
        self.assertIn("Svar från formuläret", response.text)
        self.assertIn("Om program, vilket?", response.text)
        self.assertIn("Teams", response.text)
        self.assertIn("Vilka påverkas?", response.text)
        self.assertIn("Min avdelning", response.text)
        self.assertIn("Kan inte arbeta", response.text)
        self.assertNotIn("Numret på portreplikatorn", response.text)

    def test_ticket_page_without_answers_has_no_answer_block(self):
        ticket = self.Ticket.create(
            {
                "name": "Fråga om licens",
                "description": "<p>Hur många har vi?</p>",
                "team_id": self.team.id,
                "partner_id": self.partner_portal.id,
                "category_id": self.category_other.id,
            }
        )
        response = self.url_open(f"/my/ticket/{ticket.id}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Svar från formuläret", response.text)
