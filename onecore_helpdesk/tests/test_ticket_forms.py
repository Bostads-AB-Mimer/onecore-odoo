from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from .test_mail_gateway import EMAIL_TEMPLATE


@tagged("onecore", "post_install", "-at_install")
class TestTicketForms(TransactionCase):
    """A form carries questions as an Odoo Properties definition. A form of
    kind "form" belongs to a category and is picked by the requester; a form
    of kind "addon" is pointed at by categories and asked on every ticket in
    them. A ticket's two question blocks read those definitions."""

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
        cls.addon_impact = ref("onecore_helpdesk.form_impact_addon")

    # answers to the required questions of the Påverkan add-on
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

    def _fault_ticket(self, **vals):
        """A ticket in the IT fault category with the add-on answered."""
        return self._ticket(
            category_id=self.category_fault.id, addon_properties=self.ANSWERS, **vals
        )

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

    def _read(self, ticket, field_name="properties"):
        """Read format: list of definition dicts with the ticket's values."""
        return ticket.read([field_name])[0][field_name]

    def _names(self, ticket, field_name="properties"):
        return [p["name"] for p in self._read(ticket, field_name)]

    # Seed data -----------------------------------------------------------

    def test_seeded_form_belongs_to_felanmalan_it(self):
        self.assertEqual(self.form_fault.name, "Felanmälan IT")
        self.assertEqual(self.form_fault.kind, "form")
        self.assertEqual(self.form_fault.category_id, self.category_fault)
        self.assertIn(self.form_fault, self.category_fault.form_ids)

    def test_seeded_form_has_the_errand_specific_questions(self):
        by_name = {p["name"]: p for p in self.form_fault.ticket_properties}
        self.assertEqual(list(by_name), ["port_replicator", "program"])
        self.assertEqual(by_name["port_replicator"]["type"], "char")
        self.assertEqual(by_name["program"]["type"], "selection")
        self.assertFalse(by_name["port_replicator"].get("required"))
        self.assertFalse(self.form_fault.description)

    def test_seeded_addon_carries_the_impact_questions(self):
        self.assertEqual(self.addon_impact.name, "Påverkan")
        self.assertEqual(self.addon_impact.kind, "addon")
        self.assertFalse(self.addon_impact.category_id)
        self.assertEqual(self.category_fault.addon_form_id, self.addon_impact)
        self.assertIn(self.category_fault, self.addon_impact.addon_category_ids)
        self.assertNotIn(self.addon_impact, self.category_fault.form_ids)
        self.assertIn("Här nedan väljer du", self.addon_impact.description)
        by_name = {p["name"]: p for p in self.addon_impact.ticket_properties}
        self.assertEqual(list(by_name), ["affected_scope", "impact"])
        self.assertTrue(by_name["affected_scope"]["required"])
        self.assertTrue(by_name["impact"]["required"])

    def test_other_categories_have_no_seeded_forms_or_addon(self):
        for category in (self.category_other, self.category_equipment):
            self.assertFalse(category.form_ids)
            self.assertFalse(category.addon_form_id)

    # Form kinds ------------------------------------------------------------

    def test_a_form_needs_a_category_and_an_addon_must_not_have_one(self):
        with self.assertRaises(ValidationError):
            self.Form.create({"name": "Lös", "kind": "form"})
        with self.assertRaises(ValidationError):
            self.Form.create(
                {"name": "Lös", "kind": "addon", "category_id": self.category_other.id}
            )

    def test_an_addon_can_be_shared_by_several_categories(self):
        self.category_other.addon_form_id = self.addon_impact

        ticket = self._ticket(
            category_id=self.category_other.id, addon_properties=self.ANSWERS
        )

        self.assertEqual(ticket.addon_form_id, self.addon_impact)
        self.assertEqual(ticket.addon_properties["affected_scope"], "Bara jag")
        self.assertEqual(
            self.addon_impact.addon_category_ids, self.category_fault | self.category_other
        )

    def test_ticket_counts_follow_the_kind(self):
        for _ in range(2):
            self._fault_ticket(form_id=self.form_fault.id)
        self._ticket(category_id=self.category_other.id)

        self.assertEqual(self.form_fault.ticket_count, 2)
        self.assertEqual(self.addon_impact.ticket_count, 2)
        self.assertEqual(
            self.addon_impact.action_view_tickets()["domain"],
            [("addon_form_id", "=", self.addon_impact.id)],
        )
        action = self.form_fault.action_view_tickets()
        self.assertEqual(action["domain"], [("form_id", "=", self.form_fault.id)])
        self.assertEqual(action["context"]["default_form_id"], self.form_fault.id)

    # The two blocks follow the form and the add-on -------------------------

    def test_ticket_blocks_read_the_form_and_addon_definitions(self):
        ticket = self._fault_ticket(form_id=self.form_fault.id)

        self.assertEqual(ticket.addon_form_id, self.addon_impact)
        self.assertEqual(self._names(ticket), ["port_replicator", "program"])
        self.assertEqual(self._names(ticket, "addon_properties"), ["affected_scope", "impact"])

    def test_answers_written_as_dict_round_trip(self):
        ticket = self._fault_ticket(
            form_id=self.form_fault.id,
            properties={"port_replicator": "4137-12", "program": "teams"},
        )

        # record format: a mapping, selections resolve to their label
        self.assertEqual(ticket.properties["port_replicator"], "4137-12")
        self.assertEqual(ticket.properties["program"], "Teams")
        self.assertEqual(ticket.addon_properties["affected_scope"], "Bara jag")
        keyed = ticket.with_context(property_selection_get_key=True)
        self.assertEqual(keyed.addon_properties["affected_scope"], "me")
        # read format keeps the raw key
        values = {p["name"]: p.get("value") for p in self._read(ticket, "addon_properties")}
        self.assertEqual(values["affected_scope"], "me")

    def test_answers_given_at_create_survive_without_the_containers_in_the_payload(self):
        """Odoo drops a properties value at create unless its container is in
        the values; the ticket fills form and add-on in from the category."""
        ticket = self._ticket(
            category_id=self.category_fault.id,
            properties={"program": "teams"},
            addon_properties=self.ANSWERS,
        )

        self.assertEqual(ticket.form_id, self.form_fault)
        self.assertEqual(ticket.addon_form_id, self.addon_impact)
        self.assertEqual(ticket.properties["program"], "Teams")
        self.assertEqual(ticket.addon_properties["impact"], "Kan arbeta som vanligt")

    def test_ticket_in_a_category_without_forms_or_addon_has_empty_blocks(self):
        ticket = self._ticket(category_id=self.category_other.id)

        self.assertFalse(ticket.form_id)
        self.assertFalse(ticket.addon_form_id)
        self.assertEqual(self._read(ticket), [])
        self.assertEqual(self._read(ticket, "addon_properties"), [])

    # The questions reach the browser before the ticket is saved -----------

    ONCHANGE_SPEC = {
        "team_id": {},
        "category_id": {},
        "form_id": {"fields": {"display_name": {}}},
        "addon_form_id": {"fields": {"display_name": {}}},
        "properties": {},
        "addon_properties": {},
    }

    def test_onchange_on_category_returns_both_blocks(self):
        result = self.Ticket.onchange(
            {
                "team_id": self.team.id,
                "category_id": self.category_fault.id,
                "form_id": False,
                "addon_form_id": False,
                "properties": [],
                "addon_properties": [],
            },
            ["category_id"],
            self.ONCHANGE_SPEC,
        )

        value = result["value"]
        self.assertEqual(value["form_id"]["id"], self.form_fault.id)
        self.assertEqual(value["addon_form_id"]["id"], self.addon_impact.id)
        self.assertEqual(
            [p["name"] for p in value["properties"]], ["port_replicator", "program"]
        )
        self.assertEqual(
            [p["name"] for p in value["addon_properties"]], ["affected_scope", "impact"]
        )

    def test_onchange_clearing_the_category_empties_both_blocks(self):
        ticket = self._fault_ticket(
            form_id=self.form_fault.id, properties={"port_replicator": "4137-12"}
        )

        result = ticket.onchange(
            {
                "team_id": self.team.id,
                "category_id": self.category_other.id,
                "form_id": self.form_fault.id,
                "addon_form_id": self.addon_impact.id,
                "properties": self._read(ticket),
                "addon_properties": self._read(ticket, "addon_properties"),
            },
            ["category_id"],
            self.ONCHANGE_SPEC,
        )

        self.assertFalse(result["value"]["form_id"])
        self.assertFalse(result["value"]["addon_form_id"])
        self.assertEqual(result["value"]["properties"], [])
        self.assertEqual(result["value"]["addon_properties"], [])

    # Category and form stay consistent -----------------------------------

    def test_category_with_a_single_form_preselects_it_on_create(self):
        ticket = self._fault_ticket()

        self.assertEqual(ticket.form_id, self.form_fault)

    def test_recategorising_into_a_category_with_one_form_preselects_it(self):
        ticket = self._ticket(category_id=self.category_other.id)

        # the agent answers the add-on in the same save, as in the UI
        ticket.write({"category_id": self.category_fault.id, "addon_properties": self.ANSWERS})

        self.assertEqual(ticket.form_id, self.form_fault)
        self.assertEqual(ticket.addon_form_id, self.addon_impact)
        self.assertEqual(ticket.addon_properties["impact"], "Kan arbeta som vanligt")

    def test_category_with_several_forms_does_not_preselect(self):
        self.Form.create({"name": "Skrivare", "category_id": self.category_fault.id})

        ticket = self.Ticket.new({"category_id": self.category_fault.id})

        self.assertFalse(ticket.form_id)

    def test_form_from_another_category_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._ticket(category_id=self.category_other.id, form_id=self.form_fault.id)

    def test_writing_a_form_from_another_category_keeps_the_category_and_fails(self):
        ticket = self._ticket(category_id=self.category_other.id)

        with self.assertRaises(ValidationError):
            ticket.write({"form_id": self.form_fault.id})

    def test_form_implies_its_category_on_create(self):
        ticket = self._ticket(form_id=self.form_fault.id, addon_properties=self.ANSWERS)

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

        ticket.write({"form_id": self.form_fault.id, "addon_properties": self.ANSWERS})

        self.assertEqual(ticket.category_id, self.category_fault)
        self.assertEqual(ticket.form_id, self.form_fault)

    # Category, form and required answers for everyone ----------------------

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
            self._ticket(
                user=self._employee(),
                category_id=self.category_fault.id,
                addon_properties=self.ANSWERS,
            )

    def test_a_single_form_is_preselected_for_the_user(self):
        ticket = self._ticket(
            user=self._employee(),
            category_id=self.category_fault.id,
            addon_properties=self.ANSWERS,
        )

        self.assertEqual(ticket.form_id, self.form_fault)

    def test_user_must_answer_the_required_addon_questions(self):
        with self.assertRaises(ValidationError) as error:
            self._ticket(
                user=self._employee(),
                category_id=self.category_fault.id,
                addon_properties={"affected_scope": "me"},
            )

        self.assertIn("Hur drabbas du/ni?", str(error.exception))

    def test_optional_questions_may_stay_blank(self):
        ticket = self._ticket(
            user=self._employee(),
            category_id=self.category_fault.id,
            addon_properties=self.ANSWERS,
        )

        self.assertFalse(ticket.properties["port_replicator"])

    def test_blanking_a_required_answer_later_is_rejected(self):
        employee = self._employee()
        ticket = self._ticket(
            user=employee,
            category_id=self.category_fault.id,
            addon_properties=self.ANSWERS,
        )

        with self.assertRaises(ValidationError):
            ticket.with_user(employee).write(
                {"addon_properties": {"affected_scope": "me", "impact": False}}
            )

    def test_zero_counts_as_a_required_answer(self):
        counted_form = self.Form.create(
            {
                "name": "Skrivare",
                "category_id": self.category_equipment.id,
                "ticket_properties": [
                    {"name": "pages", "string": "Antal sidor", "type": "integer", "required": True}
                ],
            }
        )

        ticket = self._ticket(
            user=self._employee(),
            category_id=self.category_equipment.id,
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
        self.assertFalse(ticket.addon_properties["impact"])

    def test_adding_a_required_question_from_a_ticket_is_allowed(self):
        """The gear editor writes the new definition through the host ticket;
        that is configuration, not answering."""
        ticket = self._fault_ticket(form_id=self.form_fault.id)
        definition = self._read(ticket)
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
            ticket.write({"properties": {"building": ""}})

    def test_adding_an_addon_question_from_a_ticket_updates_the_addon(self):
        ticket = self._fault_ticket()
        definition = self._read(ticket, "addon_properties")
        definition.append(
            {
                "name": "since_when",
                "string": "Sedan när?",
                "type": "char",
                "required": True,
                "definition_changed": True,
            }
        )

        ticket.write({"addon_properties": definition})

        names = [p["name"] for p in self.addon_impact.ticket_properties]
        self.assertEqual(names, ["affected_scope", "impact", "since_when"])

    def test_a_category_without_forms_needs_no_form(self):
        ticket = self._ticket(user=self._employee(), category_id=self.category_other.id)

        self.assertFalse(ticket.form_id)

    def test_recategorising_to_a_category_with_several_forms_requires_a_form(self):
        self.Form.create({"name": "Skrivare", "category_id": self.category_fault.id})
        employee = self._employee()
        ticket = self._ticket(user=employee, category_id=self.category_other.id)

        with self.assertRaises(ValidationError):
            ticket.with_user(employee).write(
                {"category_id": self.category_fault.id, "addon_properties": self.ANSWERS}
            )

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

    # Old answers survive in the chatter ----------------------------------

    def _notes(self, ticket, needle="Svar från formuläret"):
        return self.env["mail.message"].search(
            [
                ("model", "=", "helpdesk.ticket"),
                ("res_id", "=", ticket.id),
                ("body", "ilike", needle),
            ]
        )

    def test_changing_category_clears_both_blocks_and_logs_the_answers(self):
        ticket = self._fault_ticket(
            form_id=self.form_fault.id, properties={"port_replicator": "4137-12"}
        )

        ticket.category_id = self.category_other

        self.assertFalse(ticket.form_id)
        self.assertFalse(ticket.addon_form_id)
        self.assertEqual(self._read(ticket), [])
        self.assertEqual(self._read(ticket, "addon_properties"), [])
        notes = self._notes(ticket)
        self.assertEqual(len(notes), 2)
        form_note = notes.filtered(lambda n: "Felanmälan IT" in n.body)
        self.assertIn("4137-12", form_note.body)
        addon_note = notes.filtered(lambda n: "Påverkan" in n.body)
        self.assertIn("Bara jag", addon_note.body)

    def test_switching_form_in_the_same_category_keeps_the_addon_answers(self):
        printer_form = self._optional_form(self.category_fault)
        ticket = self._fault_ticket(
            form_id=self.form_fault.id, properties={"port_replicator": "4137-12"}
        )

        ticket.form_id = printer_form

        self.assertEqual(self._names(ticket), ["printer_model"])
        notes = self._notes(ticket)
        self.assertEqual(len(notes), 1)
        self.assertIn("4137-12", notes.body)
        self.assertEqual(ticket.addon_properties["affected_scope"], "Bara jag")

    def test_logged_answers_are_appended_to_the_description(self):
        ticket = self._fault_ticket(
            form_id=self.form_fault.id, properties={"port_replicator": "4137-12"}
        )

        ticket.category_id = self.category_other

        self.assertIn("Skrivaren fungerar inte.", ticket.description)
        self.assertIn("Numret på portreplikatorn (ex 4137-12): 4137-12", ticket.description)
        self.assertIn("Hur drabbas du/ni?: Kan arbeta som vanligt", ticket.description)

    def test_repointing_the_category_addon_logs_the_answers_on_every_ticket(self):
        ticket = self._fault_ticket(form_id=self.form_fault.id)
        other_addon = self.Form.create(
            {
                "name": "Plats",
                "kind": "addon",
                "ticket_properties": [
                    {"name": "building", "string": "Byggnad", "type": "char"}
                ],
            }
        )

        self.category_fault.addon_form_id = other_addon

        self.assertEqual(ticket.addon_form_id, other_addon)
        self.assertEqual(self._names(ticket, "addon_properties"), ["building"])
        note = self._notes(ticket)
        self.assertEqual(len(note), 1)
        self.assertIn("Påverkan", note.body)
        self.assertIn("Vilka påverkas?: Bara jag", note.body)
        self.assertIn("Vilka påverkas?: Bara jag", ticket.description)

    def test_deleting_a_question_logs_its_answers_on_every_ticket_using_the_form(self):
        first = self._fault_ticket(
            form_id=self.form_fault.id, properties={"port_replicator": "1111-11"}
        )
        second = self._fault_ticket(
            form_id=self.form_fault.id, properties={"port_replicator": "2222-22"}
        )
        definition = self._read(first)
        for prop in definition:
            if prop["name"] == "port_replicator":
                prop["definition_deleted"] = True
                prop["definition_changed"] = True

        first.write({"properties": definition})

        self.assertEqual([p["name"] for p in self.form_fault.ticket_properties], ["program"])
        for ticket, number in ((first, "1111-11"), (second, "2222-22")):
            note = self._notes(ticket, "togs bort ur formuläret")
            self.assertEqual(len(note), 1)
            self.assertIn(f"Numret på portreplikatorn (ex 4137-12): {number}", note.body)
            self.assertIn(number, ticket.description)

    def test_changing_category_without_answers_logs_nothing(self):
        ticket = self._ticket(
            category_id=self.category_equipment.id,
            form_id=self._optional_form(self.category_equipment).id,
        )

        ticket.category_id = self.category_other

        self.assertFalse(self._notes(ticket, "Svar"))

    def test_zero_is_an_answer_in_the_snapshot(self):
        counted_form = self.Form.create(
            {
                "name": "Räknare",
                "category_id": self.category_equipment.id,
                "ticket_properties": [
                    {"name": "pages", "string": "Antal sidor", "type": "integer"}
                ],
            }
        )
        ticket = self._ticket(
            category_id=self.category_equipment.id,
            form_id=counted_form.id,
            properties={"pages": 0},
        )

        ticket.form_id = self._optional_form(self.category_equipment)

        self.assertIn("Antal sidor: 0", self._notes(ticket).body)

    def test_batch_recategorisation_logs_one_form_note_per_ticket(self):
        first = self._fault_ticket(
            form_id=self.form_fault.id, properties={"port_replicator": "1111-11"}
        )
        second = self._fault_ticket(
            form_id=self.form_fault.id, properties={"port_replicator": "2222-22"}
        )

        (first | second).write({"category_id": self.category_other.id})

        first_notes = self._notes(first, "Felanmälan IT")
        self.assertEqual(len(first_notes), 1)
        self.assertIn("1111-11", first_notes.body)
        self.assertIn("2222-22", self._notes(second, "Felanmälan IT").body)

    def test_form_with_empty_definition_is_just_title_and_description(self):
        plain_form = self.Form.create(
            {"name": "Övrigt", "category_id": self.category_equipment.id}
        )

        ticket = self._ticket(category_id=self.category_equipment.id)

        self.assertEqual(ticket.form_id, plain_form)
        self.assertEqual(self._read(ticket), [])

    def test_displayed_answers_list_the_form_block_then_the_addon_block(self):
        ticket = self._fault_ticket(
            form_id=self.form_fault.id, properties={"program": "teams"}
        )

        self.assertEqual(
            ticket._displayed_answers(),
            [
                ("Om program, vilket?", "Teams"),
                ("Vilka påverkas?", "Bara jag"),
                ("Hur drabbas du/ni?", "Kan arbeta som vanligt"),
            ],
        )

    def test_datetime_answers_are_displayed_in_the_readers_time_zone(self):
        timed_form = self.Form.create(
            {
                "name": "Installation",
                "category_id": self.category_equipment.id,
                "ticket_properties": [
                    {"name": "install_at", "string": "Installation", "type": "datetime"}
                ],
            }
        )
        ticket = self._ticket(
            category_id=self.category_equipment.id,
            form_id=timed_form.id,
            properties={"install_at": "2026-11-02 08:30:00"},
        )

        # Europe/Stockholm is UTC+1 in November
        answers = ticket.with_context(tz="Europe/Stockholm")._displayed_answers()

        self.assertEqual(answers, [("Installation", "2026-11-02 09:30")])

    # Form record helpers ---------------------------------------------------

    def test_question_summary_lists_the_labels_without_separators(self):
        self.assertEqual(
            self.form_fault.question_summary,
            "Numret på portreplikatorn (ex 4137-12) · Om program, vilket?",
        )
        self.assertEqual(
            self.addon_impact.question_summary, "Vilka påverkas? * · Hur drabbas du/ni? *"
        )
        self.assertEqual(self.form_fault.category_addon_form_id, self.addon_impact)

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

    def _process_mail(self, to, msg_id, subject="Skrivaren på plan 3"):
        message = EMAIL_TEMPLATE.format(
            sender="Anna Andersson <anna.andersson@mimer.nu>",
            to=to,
            msg_id=msg_id,
            extra_headers="",
            subject=subject,
            body="Skrivaren fungerar inte.",
        )
        return self.Ticket.browse(self.env["mail.thread"].message_process(None, message))

    def test_ticket_from_mail_gets_the_default_category_and_no_form(self):
        alias_domain = self.env["mail.alias.domain"].create({"name": "test.mimer.nu"})
        self.env.company.alias_domain_id = alias_domain
        self.team.alias_name = "it-forms-test"

        ticket = self._process_mail("it-forms-test@test.mimer.nu", "<forms@test.mimer.nu>")

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

        ticket = self._process_mail(
            "ekonomi-test@test.mimer.nu", "<ekonomi@test.mimer.nu>", "Fakturafråga"
        )

        self.assertEqual(ticket.team_id, team)
        self.assertFalse(ticket.category_id)
