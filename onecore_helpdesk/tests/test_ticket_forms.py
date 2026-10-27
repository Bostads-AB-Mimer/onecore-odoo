from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from .test_mail_gateway import EMAIL_TEMPLATE


@tagged("onecore", "post_install", "-at_install")
class TestTicketForms(TransactionCase):
    """A ticket form belongs to a category and carries the extra questions
    (an Odoo Properties definition). A ticket points at one form and its
    properties read that form's definition."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env.ref
        cls.Ticket = cls.env["helpdesk.ticket"]
        cls.Form = cls.env["helpdesk.ticket.form"]
        cls.team = ref("onecore_helpdesk.team_it")
        cls.category_fault = ref("onecore_helpdesk.category_it_fault")
        cls.category_other = ref("onecore_helpdesk.category_it_other")
        cls.category_equipment = ref("onecore_helpdesk.category_equipment_order")
        cls.form_fault = ref("onecore_helpdesk.form_it_fault")

    ANSWERS = {"affected_scope": "me", "impact": "can_work"}

    def _ticket(self, user=None, **vals):
        base = {
            "name": "Skrivaren på plan 3",
            "description": "<p>Skrivaren fungerar inte.</p>",
            "team_id": self.team.id,
        }
        base.update(vals)
        model = self.Ticket.with_user(user) if user else self.Ticket
        return model.create(base)

    def _optional_form(self, category):
        """A form whose only question is optional."""
        return self.Form.create(
            {
                "name": "Skrivare",
                "category_id": category.id,
                "ticket_properties": [
                    {"name": "printer_model", "string": "Skrivarmodell", "type": "char"}
                ],
            }
        )

    # Seed data -----------------------------------------------------------

    def test_seeded_form_belongs_to_felanmalan_it(self):
        self.assertEqual(self.form_fault.name, "Felanmälan IT")
        self.assertEqual(self.form_fault.category_id, self.category_fault)
        self.assertIn(self.form_fault, self.category_fault.form_ids)

    def test_seeded_form_has_the_intranet_questions(self):
        names = [p["name"] for p in self.form_fault.ticket_properties]
        self.assertEqual(
            names, ["port_replicator", "program", "impact_info", "affected_scope", "impact"]
        )
        by_name = {p["name"]: p for p in self.form_fault.ticket_properties}
        self.assertEqual(by_name["port_replicator"]["type"], "char")
        self.assertEqual(by_name["program"]["type"], "selection")
        self.assertEqual(by_name["impact_info"]["type"], "separator")
        self.assertEqual(by_name["affected_scope"]["type"], "selection")
        self.assertEqual(by_name["impact"]["type"], "selection")
        self.assertTrue(by_name["affected_scope"]["required"])
        self.assertTrue(by_name["impact"]["required"])
        self.assertFalse(by_name["port_replicator"].get("required"))

    def test_other_categories_have_no_seeded_forms(self):
        self.assertFalse(self.category_other.form_ids)
        self.assertFalse(self.category_equipment.form_ids)

    # Properties follow the form ------------------------------------------

    def _read_properties(self, ticket):
        """Read format: list of definition dicts with the ticket's values."""
        return ticket.read(["properties"])[0]["properties"]

    def test_ticket_properties_read_the_form_definition(self):
        ticket = self._ticket(
            category_id=self.category_fault.id,
            form_id=self.form_fault.id,
            properties=self.ANSWERS,
        )

        names = [p["name"] for p in self._read_properties(ticket)]
        self.assertEqual(
            names, ["port_replicator", "program", "impact_info", "affected_scope", "impact"]
        )

    def test_answers_written_as_dict_round_trip(self):
        ticket = self._ticket(
            category_id=self.category_fault.id,
            form_id=self.form_fault.id,
            properties={"port_replicator": "4137-12", **self.ANSWERS},
        )

        # record format: a mapping, selections resolve to their label
        self.assertEqual(ticket.properties["port_replicator"], "4137-12")
        self.assertEqual(ticket.properties["affected_scope"], "Bara jag")
        self.assertFalse(ticket.properties["program"])
        keyed = ticket.with_context(property_selection_get_key=True)
        self.assertEqual(keyed.properties["affected_scope"], "me")
        # read format keeps the raw key
        values = {p["name"]: p.get("value") for p in self._read_properties(ticket)}
        self.assertEqual(values["affected_scope"], "me")

    def test_ticket_without_form_has_no_properties(self):
        ticket = self._ticket(category_id=self.category_other.id)

        self.assertFalse(ticket.form_id)
        self.assertFalse(ticket.properties)
        self.assertEqual(self._read_properties(ticket), [])

    # The questions reach the browser before the ticket is saved -----------

    ONCHANGE_SPEC = {
        "team_id": {},
        "category_id": {},
        "form_id": {"fields": {"display_name": {}}},
        "properties": {},
    }

    def test_onchange_on_category_returns_the_questions(self):
        result = self.Ticket.onchange(
            {
                "team_id": self.team.id,
                "category_id": self.category_fault.id,
                "form_id": False,
                "properties": [],
            },
            ["category_id"],
            self.ONCHANGE_SPEC,
        )

        self.assertEqual(result["value"]["form_id"]["id"], self.form_fault.id)
        names = [p["name"] for p in result["value"]["properties"]]
        self.assertEqual(
            names, ["port_replicator", "program", "impact_info", "affected_scope", "impact"]
        )

    def test_onchange_clearing_the_form_empties_the_questions(self):
        ticket = self._ticket(
            category_id=self.category_fault.id,
            form_id=self.form_fault.id,
            properties={"port_replicator": "4137-12", **self.ANSWERS},
        )

        result = ticket.onchange(
            {
                "team_id": self.team.id,
                "category_id": self.category_other.id,
                "form_id": self.form_fault.id,
                "properties": self._read_properties(ticket),
            },
            ["category_id"],
            self.ONCHANGE_SPEC,
        )

        self.assertFalse(result["value"]["form_id"])
        self.assertEqual(result["value"]["properties"], [])

    # Category and form stay consistent -----------------------------------

    def test_category_with_a_single_form_preselects_it_on_create(self):
        ticket = self._ticket(category_id=self.category_fault.id, properties=self.ANSWERS)

        self.assertEqual(ticket.form_id, self.form_fault)

    def test_recategorising_into_a_category_with_one_form_preselects_it(self):
        ticket = self._ticket(category_id=self.category_other.id)

        # the agent answers the questions in the same save, as in the UI
        ticket.write({"category_id": self.category_fault.id, "properties": self.ANSWERS})

        self.assertEqual(ticket.form_id, self.form_fault)
        self.assertEqual(ticket.properties["impact"], "Kan arbeta som vanligt")

    # Category and form are required for users creating tickets in Odoo ------

    def _employee(self):
        return self.env["res.users"].create(
            {
                "name": "Eva Employee",
                "login": "eva.employee@test.mimer.nu",
                "email": "eva.employee@test.mimer.nu",
                "group_ids": [
                    (6, 0, [self.env.ref("helpdesk_mgmt.group_helpdesk_user_own").id])
                ],
            }
        )

    def test_user_must_choose_a_category(self):
        with self.assertRaises(ValidationError):
            self._ticket(user=self._employee())

    def test_user_must_choose_a_form_when_the_category_has_several(self):
        self.Form.create({"name": "Skrivare", "category_id": self.category_fault.id})

        with self.assertRaises(ValidationError):
            self._ticket(user=self._employee(), category_id=self.category_fault.id)

    def test_a_single_form_is_preselected_for_the_user(self):
        ticket = self._ticket(user=self._employee(), category_id=self.category_fault.id, properties=self.ANSWERS
        )

        self.assertEqual(ticket.form_id, self.form_fault)

    # Required answers ----------------------------------------------------

    def test_user_must_answer_the_required_questions(self):
        with self.assertRaises(ValidationError) as error:
            self._ticket(user=self._employee(), category_id=self.category_fault.id,
                properties={"affected_scope": "me"},
            )

        self.assertIn("Hur drabbas du/ni?", str(error.exception))

    def test_optional_questions_may_stay_blank(self):
        ticket = self._ticket(user=self._employee(), category_id=self.category_fault.id, properties=self.ANSWERS
        )

        self.assertFalse(ticket.properties["port_replicator"])

    def test_blanking_a_required_answer_later_is_rejected(self):
        employee = self._employee()
        ticket = self._ticket(user=employee, category_id=self.category_fault.id, properties=self.ANSWERS
        )

        with self.assertRaises(ValidationError):
            ticket.with_user(employee).write(
                {"properties": {"affected_scope": "me", "impact": False}}
            )

    def test_zero_counts_as_a_required_answer(self):
        counted_form = self.Form.create(
            {
                "name": "Skrivare",
                "category_id": self.category_equipment.id,
                "ticket_properties": [
                    {
                        "name": "pages",
                        "string": "Antal sidor",
                        "type": "integer",
                        "required": True,
                    }
                ],
            }
        )

        ticket = self._ticket(user=self._employee(), category_id=self.category_equipment.id,
            form_id=counted_form.id,
            properties={"pages": 0},
        )

        self.assertEqual(ticket.properties["pages"], 0)

    def test_rules_apply_to_automated_callers_too(self):
        # the test environment runs as superuser
        with self.assertRaises(ValidationError):
            self._ticket(category_id=self.category_fault.id)

    def test_skip_context_key_bypasses_the_rules(self):
        ticket = self.Ticket.with_context(skip_ticket_form_rules=True).create(
            {
                "name": "Skrivaren på plan 3",
                "description": "<p>Skrivaren fungerar inte.</p>",
                "team_id": self.team.id,
                "category_id": self.category_fault.id,
            }
        )

        self.assertEqual(ticket.form_id, self.form_fault)
        self.assertFalse(ticket.properties["impact"])

    def test_adding_a_required_question_from_a_ticket_is_allowed(self):
        """The gear editor writes the new definition through the host ticket;
        that is configuration, not answering."""
        ticket = self._ticket(
            category_id=self.category_fault.id,
            form_id=self.form_fault.id,
            properties=self.ANSWERS,
        )
        definition = self._read_properties(ticket)
        definition.append(
            {
                "name": "building",
                "string": "Byggnad",
                "type": "char",
                "required": True,
                "definition_changed": True,
            }
        )

        ticket.write({"properties": definition})

        self.assertIn("building", [p["name"] for p in self.form_fault.ticket_properties])
        with self.assertRaises(ValidationError):
            ticket.write({"properties": {**self.ANSWERS, "building": ""}})

    def test_required_must_be_a_boolean_in_the_definition(self):
        with self.assertRaises(ValueError):
            self.Form.create(
                {
                    "name": "Trasig",
                    "category_id": self.category_equipment.id,
                    "ticket_properties": [
                        {"name": "x", "string": "X", "type": "char", "required": "yes"}
                    ],
                }
            )

    def test_a_category_without_forms_needs_no_form(self):
        ticket = self._ticket(user=self._employee(), category_id=self.category_other.id
        )

        self.assertFalse(ticket.form_id)

    def test_recategorising_to_a_category_with_several_forms_requires_a_form(self):
        self.Form.create({"name": "Skrivare", "category_id": self.category_fault.id})
        employee = self._employee()
        ticket = self._ticket(user=employee, category_id=self.category_other.id)

        with self.assertRaises(ValidationError):
            ticket.with_user(employee).write({"category_id": self.category_fault.id})

    def test_ticket_without_category_gets_the_team_default(self):
        # automations, scripts and the mail gateway leave the category out
        ticket = self._ticket()

        self.assertEqual(ticket.category_id, self.category_other)
        self.assertFalse(ticket.form_id)

    def test_explicit_empty_category_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            self._ticket(category_id=False)

        self.assertIn("Välj en kategori", str(error.exception))

    def test_team_without_default_category_gives_no_default(self):
        team = self.env["helpdesk.ticket.team"].create({"name": "Ekonomi"})

        with self.assertRaises(ValidationError):
            self._ticket(team_id=team.id)

    def test_category_with_several_forms_does_not_preselect(self):
        self.Form.create(
            {"name": "Skrivare", "category_id": self.category_fault.id}
        )

        ticket = self.Ticket.new({"category_id": self.category_fault.id})

        self.assertFalse(ticket.form_id)

    def _notes(self, ticket):
        return self.env["mail.message"].search(
            [
                ("model", "=", "helpdesk.ticket"),
                ("res_id", "=", ticket.id),
                ("body", "ilike", "Svar från formuläret"),
            ]
        )

    def test_changing_category_clears_the_form_and_logs_the_answers(self):
        ticket = self._ticket(
            category_id=self.category_fault.id,
            form_id=self.form_fault.id,
            properties={"port_replicator": "4137-12", **self.ANSWERS},
        )

        ticket.category_id = self.category_other

        self.assertFalse(ticket.form_id)
        self.assertEqual(self._read_properties(ticket), [])
        notes = self._notes(ticket)
        self.assertEqual(len(notes), 1)
        self.assertIn("Felanmälan IT", notes.body)
        self.assertIn("4137-12", notes.body)
        self.assertIn("Bara jag", notes.body)

    def test_switching_form_in_the_same_category_logs_the_answers(self):
        printer_form = self.Form.create(
            {
                "name": "Skrivare",
                "category_id": self.category_fault.id,
                "ticket_properties": [
                    {"name": "printer_model", "string": "Skrivarmodell", "type": "char"}
                ],
            }
        )
        ticket = self._ticket(
            category_id=self.category_fault.id,
            form_id=self.form_fault.id,
            properties={"port_replicator": "4137-12", **self.ANSWERS},
        )

        ticket.form_id = printer_form

        names = [p["name"] for p in self._read_properties(ticket)]
        self.assertEqual(names, ["printer_model"])
        self.assertIn("4137-12", self._notes(ticket).body)

    def test_changing_category_without_answers_logs_nothing(self):
        ticket = self._ticket(
            category_id=self.category_equipment.id,
            form_id=self._optional_form(self.category_equipment).id,
        )

        ticket.category_id = self.category_other

        self.assertFalse(self._notes(ticket))

    def test_form_implies_its_category_on_create(self):
        ticket = self._ticket(form_id=self.form_fault.id, properties=self.ANSWERS)

        self.assertEqual(ticket.category_id, self.category_fault)
        self.assertEqual(ticket.form_id, self.form_fault)

    def test_form_implies_its_category_on_write(self):
        # an old ticket without category, e.g. mail to a team without default
        ticket = self.Ticket.with_context(skip_ticket_form_rules=True).create(
            {
                "name": "Skrivaren på plan 3",
                "description": "<p>Skrivaren fungerar inte.</p>",
                "team_id": self.team.id,
                "category_id": False,
            }
        )
        self.assertFalse(ticket.category_id)

        ticket.write({"form_id": self.form_fault.id, "properties": self.ANSWERS})

        self.assertEqual(ticket.category_id, self.category_fault)
        self.assertEqual(ticket.form_id, self.form_fault)

    def test_form_from_another_category_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._ticket(
                category_id=self.category_other.id, form_id=self.form_fault.id
            )

    def test_writing_a_form_from_another_category_keeps_the_category_and_fails(self):
        ticket = self._ticket(category_id=self.category_other.id)

        with self.assertRaises(ValidationError):
            ticket.write({"form_id": self.form_fault.id})

    def test_zero_is_an_answer_in_the_snapshot(self):
        counted_form = self.Form.create(
            {
                "name": "Skrivare",
                "category_id": self.category_fault.id,
                "ticket_properties": [
                    {"name": "pages", "string": "Antal sidor", "type": "integer"}
                ],
            }
        )
        ticket = self._ticket(
            category_id=self.category_fault.id,
            form_id=counted_form.id,
            properties={"pages": 0},
        )

        ticket.form_id = self._optional_form(self.category_fault)

        self.assertIn("Antal sidor: 0", self._notes(ticket).body)

    def test_batch_recategorisation_logs_one_note_per_ticket(self):
        first = self._ticket(
            category_id=self.category_fault.id,
            form_id=self.form_fault.id,
            properties={"port_replicator": "1111-11", **self.ANSWERS},
        )
        second = self._ticket(
            category_id=self.category_fault.id,
            form_id=self.form_fault.id,
            properties={"port_replicator": "2222-22", **self.ANSWERS},
        )

        (first | second).write({"category_id": self.category_other.id})

        self.assertIn("1111-11", self._notes(first).body)
        self.assertIn("2222-22", self._notes(second).body)
        self.assertEqual(len(self._notes(first)), 1)

    def test_form_with_empty_definition_is_just_title_and_description(self):
        plain_form = self.Form.create(
            {"name": "Övrigt", "category_id": self.category_equipment.id}
        )

        ticket = self._ticket(category_id=self.category_equipment.id)

        self.assertEqual(ticket.form_id, plain_form)
        self.assertEqual(self._read_properties(ticket), [])

    # Form record helpers --------------------------------------------------

    def test_question_summary_lists_the_labels_without_separators(self):
        self.assertEqual(
            self.form_fault.question_summary,
            "Numret på portreplikatorn (ex 4137-12) · Om program, vilket? · "
            "Vilka påverkas? * · Hur drabbas du/ni? *",
        )

    def test_ticket_count_and_action_cover_the_forms_tickets(self):
        for _ in range(2):
            self._ticket(
                category_id=self.category_fault.id,
                form_id=self.form_fault.id,
                properties=self.ANSWERS,
            )
        self._ticket(category_id=self.category_other.id)

        self.assertEqual(self.form_fault.ticket_count, 2)
        action = self.form_fault.action_view_tickets()
        self.assertEqual(action["domain"], [("form_id", "=", self.form_fault.id)])
        self.assertEqual(action["context"]["default_form_id"], self.form_fault.id)

    def test_portal_users_only_see_portal_forms(self):
        hidden = self.Form.create(
            {
                "name": "Internt",
                "category_id": self.category_fault.id,
                "show_in_portal": False,
            }
        )
        portal_user = self.env["res.users"].create(
            {
                "name": "Portal Persson",
                "login": "portal.persson@test.mimer.nu",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )

        visible = self.Form.with_user(portal_user).search([])

        self.assertIn(self.form_fault, visible)
        self.assertNotIn(hidden, visible)

    # Email tickets -------------------------------------------------------

    def test_ticket_from_mail_gets_the_default_category_and_no_form(self):
        alias_domain = self.env["mail.alias.domain"].create({"name": "test.mimer.nu"})
        self.env.company.alias_domain_id = alias_domain
        self.team.alias_name = "it-forms-test"
        message = EMAIL_TEMPLATE.format(
            sender="Anna Andersson <anna.andersson@mimer.nu>",
            to="it-forms-test@test.mimer.nu",
            msg_id="<forms@test.mimer.nu>",
            extra_headers="",
            subject="Skrivaren på plan 3",
            body="Skrivaren fungerar inte.",
        )

        ticket_id = self.env["mail.thread"].message_process(None, message)

        ticket = self.Ticket.browse(ticket_id)
        self.assertEqual(ticket.team_id, self.team)
        self.assertEqual(ticket.category_id, self.category_other)
        self.assertFalse(ticket.form_id)
        self.assertFalse(ticket.properties)

    def test_mail_to_a_team_without_default_category_is_not_rejected(self):
        alias_domain = self.env["mail.alias.domain"].create({"name": "test.mimer.nu"})
        self.env.company.alias_domain_id = alias_domain
        team = self.env["helpdesk.ticket.team"].create(
            {"name": "Ekonomi", "alias_name": "ekonomi-test"}
        )
        message = EMAIL_TEMPLATE.format(
            sender="Anna Andersson <anna.andersson@mimer.nu>",
            to="ekonomi-test@test.mimer.nu",
            msg_id="<ekonomi@test.mimer.nu>",
            extra_headers="",
            subject="Fakturafråga",
            body="Var är fakturan?",
        )

        ticket_id = self.env["mail.thread"].message_process(None, message)

        ticket = self.Ticket.browse(ticket_id)
        self.assertEqual(ticket.team_id, team)
        self.assertFalse(ticket.category_id)
