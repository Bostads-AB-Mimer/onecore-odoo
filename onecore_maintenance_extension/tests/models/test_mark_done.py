"""Markera som utförd: an outcome for every component, a summary in the
chatter and the move to Utförd in one call."""

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged
from odoo.tests.common import TransactionCase

from ..utils.test_utils import (
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_request,
    create_maintenance_team,
)
from .test_maintenance_request_component import _apartment_request, _link_vals


def _surface_vals(component_id="comp-golv", label="Golv", **kwargs):
    return _link_vals(
        component_id,
        label,
        subtype_name="Linoleum",
        category_type="SURFACE",
        **kwargs,
    )


class MarkDoneCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.utford = self.env.ref("maintenance.stage_5")

    def _request(self, *link_vals, assign=True, **kwargs):
        """A Lägenhet ärende with these components, with a resource assigned
        unless assign=False."""
        request = _apartment_request(self.env, **kwargs)
        if link_vals:
            request.write(
                {"component_ids": [Command.create(vals) for vals in link_vals]}
            )
        if assign:
            request.with_user(self.internal_user).write(
                {"user_id": self.internal_user.id}
            )
        return self.env["maintenance.request"].browse(request.id)

    def _answers(self, request, outcome="REPAIRED", note=""):
        return [
            {"id": component.id, "outcome": outcome, "note": note}
            for component in request.component_ids
        ]

    def _register(self, request, outcomes, user=None, row_ids=None):
        if row_ids is None:
            row_ids = request.component_ids.ids
        return request.with_user(user or self.internal_user).action_register_outcomes(
            outcomes, row_ids
        )

    def _messages(self, request):
        return self.env["mail.message"].search(
            [("model", "=", "maintenance.request"), ("res_id", "=", request.id)]
        )

    def _move(self, request, xml_id):
        request.with_user(self.internal_user).write(
            {"stage_id": self.env.ref(xml_id).id}
        )


@tagged("onecore")
class TestOutcomeOptions(TransactionCase):
    def _options(self, category_type):
        component = self.env["maintenance.request.component"].new(
            {"category_type": category_type}
        )
        return component._outcome_options()

    def test_equipment_gets_reparerad_utbytt_ingen_atgard(self):
        self.assertEqual(
            self._options("EQUIPMENT"),
            [
                ("REPAIRED", "Reparerad"),
                ("REPLACED", "Utbytt"),
                ("NO_ACTION", "Ingen åtgärd"),
            ],
        )

    def test_surface_gets_atgardad_fornyad_ingen_atgard(self):
        self.assertEqual(
            self._options("SURFACE"),
            [
                ("REMEDIED", "Åtgärdad"),
                ("RENEWED", "Förnyad"),
                ("NO_ACTION", "Ingen åtgärd"),
            ],
        )

    def test_without_category_type_counts_as_equipment(self):
        self.assertEqual(self._options(False), self._options("EQUIPMENT"))


@tagged("onecore")
class TestRegisterOutcomes(MarkDoneCase):
    def test_one_save_stores_outcomes_posts_summary_and_moves_to_utford(self):
        request = self._request(_link_vals(), _surface_vals())
        frys = request.component_ids.filtered(lambda c: c.component_name == "Frys")
        golv = request.component_ids.filtered(lambda c: c.component_name == "Golv")
        messages_before = self._messages(request)

        self._register(
            request,
            [
                {"id": frys.id, "outcome": "REPAIRED", "note": "  Bytt termostat "},
                {"id": golv.id, "outcome": "RENEWED", "note": ""},
            ],
        )

        self.assertEqual(request.stage_id, self.utford)
        self.assertTrue(request.performed_date)
        self.assertEqual(frys.outcome, "REPAIRED")
        self.assertEqual(frys.outcome_note, "Bytt termostat")
        self.assertEqual(golv.outcome, "RENEWED")
        self.assertFalse(golv.outcome_note)
        self.assertEqual(
            (frys | golv).outcome_user_id, self.internal_user
        )

        new_messages = self._messages(request) - messages_before
        summary = new_messages.filtered(lambda m: "Utfall registrerat" in (m.body or ""))
        self.assertEqual(len(summary), 1)
        self.assertIn("Frys (Kök):</strong> Reparerad – Bytt termostat", summary.body)
        self.assertIn("Golv – Linoleum (Kök):</strong> Förnyad", summary.body)
        self.assertEqual(summary.subtype_id, self.env.ref("mail.mt_note"))
        self.assertEqual(summary.author_id, self.internal_user.partner_id)
        # The stage change logs itself as usual ("Status: … → Utförd")
        self.assertTrue(
            (new_messages - summary).filtered(lambda m: "Utförd" in (m.body or ""))
        )

    def test_note_is_escaped_in_the_chatter(self):
        request = self._request(_link_vals())

        self._register(request, self._answers(request, note="<b>Bytt</b>"))

        summary = self._messages(request).filtered(
            lambda m: "Utfall registrerat" in m.body
        )
        self.assertIn("&lt;b&gt;Bytt&lt;/b&gt;", summary.body)

    def _assert_nothing_saved(self, request, messages_before):
        self.env.invalidate_all()
        self.assertNotEqual(request.stage_id, self.utford)
        self.assertFalse(request.component_ids.filtered("outcome"))
        self.assertFalse(request.component_ids.outcome_user_id)
        self.assertEqual(self._messages(request), messages_before)

    def test_missing_priority_rolls_everything_back(self):
        request = self._request(_link_vals())
        request.with_user(self.internal_user).write({"priority_expanded": False})
        messages_before = self._messages(request)

        with self.assertRaises(UserError):
            self._register(request, self._answers(request))

        self._assert_nothing_saved(request, messages_before)

    def test_nobody_assigned_rolls_everything_back(self):
        request = self._request(_link_vals(), assign=False)
        messages_before = self._messages(request)

        with self.assertRaises(UserError):
            self._register(request, self._answers(request))

        self._assert_nothing_saved(request, messages_before)

    def test_caller_that_catches_the_refusal_keeps_nothing(self):
        request = self._request(_link_vals())
        request.with_user(self.internal_user).write({"priority_expanded": False})
        messages_before = self._messages(request)

        try:
            self._register(request, self._answers(request))
        except UserError:
            pass

        self._assert_nothing_saved(request, messages_before)

    def test_malformed_payload_is_refused_with_a_message(self):
        request = self._request(_link_vals())
        component = request.component_ids

        for outcomes, row_ids in (
            ([{"id": [component.id], "outcome": "REPAIRED"}], [component.id]),
            ([{"id": component.id, "outcome": ["REPAIRED"]}], [component.id]),
            ([{"id": component.id, "outcome": "REPAIRED"}], [[component.id]]),
            (["REPAIRED"], [component.id]),
        ):
            with self.subTest(outcomes=outcomes, row_ids=row_ids):
                with self.assertRaises(UserError):
                    self._register(request, outcomes, row_ids=row_ids)

        self.assertFalse(request.component_ids.filtered("outcome"))

    def test_contractor_on_their_teams_arende_registers_outcomes(self):
        contractor = create_external_contractor_user(self.env)
        team = create_maintenance_team(self.env, member_ids=[Command.link(contractor.id)])
        request = self._request(_link_vals(), maintenance_team_id=team.id)

        self._register(request, self._answers(request, "NO_ACTION"), user=contractor)

        self.assertEqual(request.stage_id, self.utford)
        self.assertEqual(request.component_ids.outcome, "NO_ACTION")
        self.assertEqual(request.component_ids.outcome_user_id, contractor)

    def test_contractor_is_refused_once_utford(self):
        contractor = create_external_contractor_user(self.env)
        team = create_maintenance_team(self.env, member_ids=[Command.link(contractor.id)])
        request = self._request(_link_vals(), maintenance_team_id=team.id)
        self._move(request, "maintenance.stage_5")

        with self.assertRaises(UserError):
            self._register(request, self._answers(request), user=contractor)

        self.assertFalse(request.component_ids.outcome)

    def test_internal_user_is_refused_once_utford(self):
        request = self._request(_link_vals())
        self._register(request, self._answers(request, "REPAIRED"))

        with self.assertRaises(UserError):
            self._register(request, self._answers(request, "REPLACED"))

        self.assertEqual(request.component_ids.outcome, "REPAIRED")

    def test_arende_that_isnt_a_lagenhet_is_refused(self):
        request = create_maintenance_request(self.env, space_caption="Tvättstuga")

        with self.assertRaises(UserError):
            self._register(request, [])

    def test_inactive_arende_is_refused(self):
        request = self._request(_link_vals())
        request.with_user(self.internal_user).write({"archive": True})

        with self.assertRaises(UserError):
            self._register(request, self._answers(request))

        self.assertNotEqual(request.stage_id, self.utford)

    def test_line_breaks_in_a_note_are_kept_in_the_chatter(self):
        request = self._request(_link_vals())

        self._register(
            request, self._answers(request, note="Bytt termostat\nKontrollerat tätning")
        )

        summary = self._messages(request).filtered(
            lambda m: "Utfall registrerat" in m.body
        )
        self.assertRegex(summary.body, r"Bytt termostat<br\s*/?>Kontrollerat tätning")

    def test_every_component_needs_an_outcome(self):
        # A component uninstalled since it was chosen is shown as "(borttagen)"
        # in the grid; it is an ordinary row and needs an outcome too
        request = self._request(
            _link_vals(), _link_vals("comp-borttagen", "Diskmaskin")
        )
        frys = request.component_ids.filtered(lambda c: c.component_name == "Frys")
        removed = request.component_ids - frys

        for outcomes in (
            [{"id": frys.id, "outcome": "REPAIRED"}],
            [
                {"id": frys.id, "outcome": "REPAIRED"},
                {"id": removed.id, "outcome": ""},
            ],
            [
                {"id": frys.id, "outcome": "REPAIRED"},
                {"id": removed.id, "outcome": False},
            ],
        ):
            with self.subTest(outcomes=outcomes), self.assertRaises(UserError):
                self._register(request, outcomes)

        self.assertFalse(request.component_ids.filtered("outcome"))

    def test_outcomes_offered_per_category_type_are_accepted(self):
        for vals, outcome in (
            (_link_vals(), "REPAIRED"),
            (_link_vals(), "REPLACED"),
            (_link_vals(), "NO_ACTION"),
            (_link_vals(category_type=False), "REPAIRED"),
            (_surface_vals(), "REMEDIED"),
            (_surface_vals(), "RENEWED"),
            (_surface_vals(), "NO_ACTION"),
        ):
            with self.subTest(category_type=vals["category_type"], outcome=outcome):
                request = self._request(vals)

                self._register(request, self._answers(request, outcome))

                self.assertEqual(request.component_ids.outcome, outcome)

    def test_outcome_of_the_other_category_type_is_refused(self):
        for vals, outcome in (
            (_link_vals(), "REMEDIED"),
            (_link_vals(), "RENEWED"),
            (_surface_vals(), "REPAIRED"),
            (_surface_vals(), "REPLACED"),
            (_link_vals(), "BROKEN"),
        ):
            with self.subTest(category_type=vals["category_type"], outcome=outcome):
                request = self._request(vals)

                with self.assertRaises(UserError):
                    self._register(request, self._answers(request, outcome))

    def test_changed_components_are_refused(self):
        request = self._request(_link_vals(), _link_vals("comp-spis", "Spis"))
        frys, spis = request.component_ids.sorted("component_name")
        answers = self._answers(request)

        with self.subTest("a component removed since the flow opened"):
            with self.assertRaises(UserError):
                self._register(request, answers[:1], row_ids=[frys.id])

        with self.subTest("a component added since the flow opened"):
            with self.assertRaises(UserError):
                self._register(
                    request, answers, row_ids=[frys.id, spis.id, spis.id + 1000]
                )

        with self.subTest("an outcome for a component not on the ärende"):
            with self.assertRaises(UserError):
                self._register(
                    request, answers + [{"id": spis.id + 1000, "outcome": "REPAIRED"}]
                )

        self.assertFalse(request.component_ids.filtered("outcome"))

    def test_arende_without_components_is_refused(self):
        # It goes to Utförd from the status bar instead
        request = self._request()

        with self.assertRaises(UserError):
            self._register(request, [])

        self.assertNotEqual(request.stage_id, self.utford)

    def test_user_without_access_to_arenden_is_refused(self):
        request = self._request(_link_vals())
        portal_user = new_test_user(
            self.env, login="portal_mark_done", groups="base.group_portal"
        )

        with self.assertRaises(AccessError):
            self._register(request, self._answers(request), user=portal_user)


@tagged("onecore")
class TestOutcomeFields(MarkDoneCase):
    """The outcome fields hold to their rules however they are written."""

    def test_outcome_that_doesnt_fit_the_category_type_is_refused(self):
        request = self._request(_link_vals(), _surface_vals())
        frys = request.component_ids.filtered(lambda c: c.component_name == "Frys")
        golv = request.component_ids - frys

        with self.assertRaises(ValidationError):
            frys.with_user(self.internal_user).write({"outcome": "RENEWED"})
        with self.assertRaises(ValidationError):
            golv.with_user(self.internal_user).write({"outcome": "REPAIRED"})

    def test_outcome_user_is_whoever_writes_the_outcome(self):
        other = create_internal_user(self.env)
        request = self._request(_link_vals())
        component = request.component_ids.with_user(self.internal_user)

        component.write({"outcome": "REPAIRED", "outcome_user_id": other.id})
        self.assertEqual(component.outcome_user_id, self.internal_user)

        component.write({"outcome_user_id": other.id})
        self.assertEqual(component.outcome_user_id, self.internal_user)

        component.write({"outcome": False})
        self.assertFalse(component.outcome_user_id)

    def test_same_outcome_written_again_keeps_its_author(self):
        other = create_internal_user(self.env)
        request = self._request(_link_vals())
        request.component_ids.with_user(self.internal_user).write({"outcome": "REPAIRED"})

        request.component_ids.with_user(other).write(
            {"outcome": "REPAIRED", "outcome_note": "Kontrollerad"}
        )
        self.assertEqual(request.component_ids.outcome_user_id, self.internal_user)

        request.component_ids.with_user(other).write({"outcome": "REPLACED"})
        self.assertEqual(request.component_ids.outcome_user_id, other)

    def test_outcome_user_on_create_ignores_a_context_default(self):
        other = create_internal_user(self.env)
        request = self._request()
        Component = (
            self.env["maintenance.request.component"]
            .with_user(self.internal_user)
            .with_context(default_outcome_user_id=other.id)
        )

        with_outcome = Component.create(
            {"maintenance_request_id": request.id, "outcome": "REPAIRED", **_link_vals()}
        )
        without_outcome = Component.create(
            {"maintenance_request_id": request.id, **_link_vals("comp-spis", "Spis")}
        )

        self.assertEqual(with_outcome.outcome_user_id, self.internal_user)
        self.assertFalse(without_outcome.outcome_user_id)


@tagged("onecore")
class TestCheckCanMarkDone(MarkDoneCase):
    def _check(self, request, user=None):
        return request.with_user(user or self.internal_user).check_can_mark_done()

    def test_returns_the_components_with_their_outcomes(self):
        request = self._request(
            _surface_vals(note="Bucklar"),
            _link_vals(space_name="Badrum", space_sequence=2),
        )

        result = self._check(request)

        self.assertFalse(result["error"])
        self.assertFalse(result["contractor"])
        golv, frys = request.component_ids
        self.assertEqual(
            result["components"],
            [
                {
                    "id": golv.id,
                    "name": "Golv",
                    "subtype_name": "Linoleum",
                    "space_name": "Kök",
                    "note": "Bucklar",
                    "outcomes": [
                        ("REMEDIED", "Åtgärdad"),
                        ("RENEWED", "Förnyad"),
                        ("NO_ACTION", "Ingen åtgärd"),
                    ],
                    "outcome": False,
                    "outcome_note": "",
                },
                {
                    "id": frys.id,
                    "name": "Frys",
                    "subtype_name": "",
                    "space_name": "Badrum",
                    "note": "",
                    "outcomes": [
                        ("REPAIRED", "Reparerad"),
                        ("REPLACED", "Utbytt"),
                        ("NO_ACTION", "Ingen åtgärd"),
                    ],
                    "outcome": False,
                    "outcome_note": "",
                },
            ],
        )

    def test_tells_a_contractor_they_are_one(self):
        contractor = create_external_contractor_user(self.env)
        team = create_maintenance_team(self.env, member_ids=[Command.link(contractor.id)])
        request = self._request(_link_vals(), maintenance_team_id=team.id)

        result = self._check(request, contractor)

        self.assertFalse(result["error"])
        self.assertTrue(result["contractor"])

    def test_explains_a_missing_priority(self):
        request = self._request(_link_vals())
        request.with_user(self.internal_user).write({"priority_expanded": False})

        result = self._check(request)

        self.assertIn("Prioritet måste anges", result["error"])
        self.assertEqual(result["components"], [])

    def test_explains_that_nobody_is_assigned(self):
        request = self._request(_link_vals(), assign=False)

        result = self._check(request)

        self.assertIn("Ingen resurs är tilldelad", result["error"])

    def test_explains_that_the_arende_is_already_utford(self):
        request = self._request(_link_vals())
        self._move(request, "maintenance.stage_5")

        result = self._check(request)

        self.assertIn("redan", result["error"])

    def test_explains_that_the_arende_is_inactive(self):
        request = self._request(_link_vals())
        request.with_user(self.internal_user).write({"archive": True})

        result = self._check(request)

        self.assertIn("inaktivt", result["error"])

    def test_explains_that_the_user_cant_change_the_arende(self):
        request = self._request(_link_vals())
        readers = self.env["res.groups"].create({"name": "Läser ärenden"})
        self.env["ir.model.access"].create(
            {
                "name": "Läser ärenden",
                "model_id": self.env.ref("maintenance.model_maintenance_request").id,
                "group_id": readers.id,
                "perm_read": True,
            }
        )
        reader = new_test_user(self.env, login="md_reader", groups="base.group_portal")
        reader.group_ids |= readers

        result = self._check(request, reader)

        self.assertIn("behörighet", result["error"])
        self.assertEqual(result["components"], [])

    def test_returns_the_stored_outcomes_of_a_reopened_arende(self):
        request = self._request(_link_vals())
        self._register(request, self._answers(request, "REPLACED", "Ny frys"))
        self._move(request, "maintenance.stage_3")

        result = self._check(request)

        self.assertFalse(result["error"])
        self.assertEqual(
            (result["components"][0]["outcome"], result["components"][0]["outcome_note"]),
            ("REPLACED", "Ny frys"),
        )

    def test_explains_that_the_arende_has_no_components(self):
        request = self._request()

        result = self._check(request)

        self.assertIn("inga valda komponenter", result["error"])

    def test_explains_that_only_lagenhet_arenden_have_it(self):
        request = create_maintenance_request(self.env, space_caption="Tvättstuga")

        result = self._check(request)

        self.assertIn("lägenhet", result["error"])

    def test_user_without_access_to_arenden_is_refused(self):
        request = self._request(_link_vals())
        portal_user = new_test_user(
            self.env, login="portal_check_mark_done", groups="base.group_portal"
        )

        with self.assertRaises(AccessError):
            self._check(request, portal_user)


@tagged("onecore")
class TestCanMarkDone(MarkDoneCase):
    def test_saved_lagenhet_arende_can_be_marked_done(self):
        request = self._request(_link_vals())

        self.assertTrue(request.can_mark_done)

    def test_also_without_a_resource(self):
        # The flow explains what is missing when it opens
        request = self._request(_link_vals(), assign=False)

        self.assertTrue(request.can_mark_done)

    def test_also_while_the_form_is_being_edited(self):
        request = self._request(_link_vals())

        in_form = self.env["maintenance.request"].new({}, origin=request)

        self.assertTrue(in_form.can_mark_done)

    def test_not_without_components(self):
        request = self._request()

        self.assertFalse(request.can_mark_done)

    def test_follows_components_chosen_in_the_form(self):
        request = self._request()
        in_form = self.env["maintenance.request"].new({}, origin=request)

        in_form.component_ids = [Command.create(_link_vals())]

        self.assertTrue(in_form.can_mark_done)

    def test_not_on_an_inactive_arende(self):
        request = self._request(_link_vals())

        request.with_user(self.internal_user).write({"archive": True})

        self.assertFalse(request.can_mark_done)

    def test_not_on_an_unsaved_arende(self):
        record = self.env["maintenance.request"].new({"space_caption": "Lägenhet"})

        self.assertFalse(record.can_mark_done)

    def test_not_on_an_arende_that_isnt_a_lagenhet(self):
        request = create_maintenance_request(self.env, space_caption="Tvättstuga")

        self.assertFalse(request.can_mark_done)

    def test_not_in_utford_avslutad_or_atersand(self):
        for xml_id in (
            "maintenance.stage_5",
            "maintenance.stage_6",
            "onecore_maintenance_extension.stage_atersand",
        ):
            with self.subTest(stage=xml_id):
                request = self._request(_link_vals())

                self._move(request, xml_id)

                self.assertFalse(request.can_mark_done)


@tagged("onecore")
class TestMarkDoneFormView(TransactionCase):
    def test_button_in_the_header_follows_can_mark_done(self):
        view = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_form_extension"
        )
        arch = etree.fromstring(view.arch_db)

        widgets = arch.xpath('//widget[@name="mark_done_button"]')
        self.assertEqual(len(widgets), 1)
        self.assertEqual(widgets[0].get("invisible"), "not can_mark_done")
        self.assertEqual(len(arch.xpath('//field[@name="can_mark_done"]')), 1)

        full_arch = etree.fromstring(
            self.env["maintenance.request"].get_view(view_type="form")["arch"]
        )
        self.assertEqual(len(full_arch.xpath('//header/widget[@name="mark_done_button"]')), 1)
