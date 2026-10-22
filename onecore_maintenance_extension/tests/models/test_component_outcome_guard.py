"""A Lägenhet ärende with components moves to Utförd or Avslutad only when
every component has an outcome. Utförd → Avslutad passes, and so does
Avslutad when nobody is assigned."""

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from ..utils.test_utils import create_external_contractor_user, create_maintenance_team
from .test_maintenance_request_component import _apartment_request, _link_vals
from .test_mark_done import MarkDoneCase, _surface_vals


@tagged("onecore")
class TestComponentOutcomeGuard(MarkDoneCase):
    def setUp(self):
        super().setUp()
        self.closed_stage = self.env.ref("maintenance.stage_6")

    def _refusal(self, move):
        with self.assertRaises(UserError) as refused:
            move()
        return refused.exception.args[0]

    def _contractor_request(self, *link_vals):
        contractor = create_external_contractor_user(self.env)
        team = create_maintenance_team(self.env, member_ids=[Command.link(contractor.id)])
        request = self._request(*link_vals, maintenance_team_id=team.id)
        return request, request.with_user(contractor)

    def test_component_without_outcome_stops_the_move_to_done(self):
        request = self._request(_link_vals())
        stage_before = request.stage_id

        message = self._refusal(lambda: self._move(request, "maintenance.stage_5"))

        self.assertTrue(message.startswith(f"od-{request.id}: "))
        self.assertIn(f"kan flyttas till {self.done_stage.name}.", message)
        self.assertIn('Använd knappen "Markera som utförd".', message)
        self.assertIn("Saknar utfall: Frys (Kök).", message)
        self.assertEqual(request.stage_id, stage_before)

    def test_and_the_move_straight_to_closed(self):
        for xml_id in ("maintenance.stage_1", "maintenance.stage_3", "maintenance.stage_4"):
            with self.subTest(from_stage=xml_id):
                request = self._request(_link_vals())
                self._move(request, xml_id)

                message = self._refusal(lambda: self._move(request, "maintenance.stage_6"))

                self.assertIn(f"kan flyttas till {self.closed_stage.name}.", message)
                self.assertEqual(request.stage_id, self.env.ref(xml_id))

    def test_contractor_is_refused_too(self):
        request, as_contractor = self._contractor_request(_link_vals())

        message = self._refusal(lambda: as_contractor.write({"stage_id": self.done_stage.id}))

        self.assertIn("Markera som utförd", message)
        self.assertNotEqual(request.stage_id, self.done_stage)

    def test_request_without_components_moves_as_before(self):
        for xml_id in ("maintenance.stage_5", "maintenance.stage_6"):
            with self.subTest(stage=xml_id):
                request = self._request()

                self._move(request, xml_id)

                self.assertEqual(request.stage_id, self.env.ref(xml_id))

    def test_moves_when_every_component_has_an_outcome(self):
        request = self._request(_link_vals(), _surface_vals())
        request.component_ids.with_user(self.internal_user).write(
            {"outcome": "NO_ACTION"}
        )

        self._move(request, "maintenance.stage_5")

        self.assertEqual(request.stage_id, self.done_stage)

    def test_lists_only_the_components_without_outcome(self):
        request = self._request(_link_vals(outcome="REPAIRED"), _surface_vals())

        message = self._refusal(lambda: self._move(request, "maintenance.stage_5"))

        self.assertIn("Saknar utfall: Golv – Linoleum (Kök).", message)
        self.assertNotIn("Frys", message)

    def test_component_saved_with_the_stage_is_checked(self):
        # The status bar saves pending changes and the new stage together
        request, as_contractor = self._contractor_request(_link_vals(outcome="REPAIRED"))

        message = self._refusal(
            lambda: as_contractor.write(
                {
                    "component_ids": [Command.create(_link_vals("comp-spis", "Spis"))],
                    "stage_id": self.done_stage.id,
                }
            )
        )

        self.assertIn("Saknar utfall: Spis (Kök).", message)
        self.assertNotEqual(request.stage_id, self.done_stage)

    def test_outcome_saved_with_the_stage_counts(self):
        request = self._request(_link_vals())

        request.with_user(self.internal_user).write(
            {
                "component_ids": [
                    Command.update(request.component_ids.id, {"outcome": "NO_ACTION"})
                ],
                "stage_id": self.done_stage.id,
            }
        )

        self.assertEqual(request.stage_id, self.done_stage)

    def test_done_to_closed_passes_without_outcomes(self):
        request = self._request(_link_vals(outcome="REPAIRED"))
        self._move(request, "maintenance.stage_5")
        # A component added after Utförd
        request.with_user(self.internal_user).write(
            {"component_ids": [Command.create(_link_vals("comp-spis", "Spis"))]}
        )

        self._move(request, "maintenance.stage_6")

        self.assertEqual(request.stage_id, self.closed_stage)

    def test_unassigned_request_closes_without_outcomes(self):
        request = self._request(_link_vals(), assign=False)
        self.assertEqual(request.stage_id, self.env.ref("maintenance.stage_0"))

        self._move(request, "maintenance.stage_6")

        self.assertEqual(request.stage_id, self.closed_stage)

    def test_returned_request_closes_without_outcomes(self):
        # Återsänd clears the resource
        request = self._request(_link_vals())
        self._move(request, "onecore_maintenance_extension.stage_atersand")

        self._move(request, "maintenance.stage_6")

        self.assertEqual(request.stage_id, self.closed_stage)

    def test_waiting_with_a_resource_to_closed_is_refused(self):
        # Påbörjad → Väntar på handläggning keeps the resource
        request = self._request(_link_vals())
        self._move(request, "maintenance.stage_3")
        self._move(request, "maintenance.stage_0")
        self.assertTrue(request.user_id)

        message = self._refusal(lambda: self._move(request, "maintenance.stage_6"))

        self.assertIn('Använd knappen "Markera som utförd".', message)
        self.assertEqual(request.stage_id, self.env.ref("maintenance.stage_0"))

    def test_closed_back_to_done_points_to_an_open_stage(self):
        # The button is hidden in Avslutad
        request = self._request(_link_vals(outcome="REPAIRED"))
        self._move(request, "maintenance.stage_5")
        self._move(request, "maintenance.stage_6")
        request.component_ids.write({"outcome": False})

        message = self._refusal(lambda: self._move(request, "maintenance.stage_5"))

        self.assertIn(
            'Flytta det först till en pågående status och använd sedan knappen '
            '"Markera som utförd".',
            message,
        )
        self.assertEqual(request.stage_id, self.closed_stage)

    def test_returned_to_done_points_to_an_open_stage(self):
        request = self._request(_link_vals())
        self._move(request, "onecore_maintenance_extension.stage_atersand")

        message = self._refusal(
            lambda: request.with_user(self.internal_user).write(
                {"user_id": self.internal_user.id, "stage_id": self.done_stage.id}
            )
        )

        self.assertIn("Flytta det först till en pågående status", message)
        self.assertEqual(
            request.stage_id,
            self.env.ref("onecore_maintenance_extension.stage_atersand"),
        )

    def test_writing_the_same_stage_again_passes(self):
        request = self._request(_link_vals(outcome="REPAIRED"))
        self._move(request, "maintenance.stage_5")
        request.component_ids.write({"outcome": False})

        self._move(request, "maintenance.stage_5")

        self.assertEqual(request.stage_id, self.done_stage)

    def test_request_that_isnt_an_apartment_any_more_passes(self):
        # Its components stay, hidden, and it has no "Markera som utförd"
        request = self._request(_link_vals())
        request.write({"space_caption": "Tvättstuga"})

        self._move(request, "maintenance.stage_5")

        self.assertEqual(request.stage_id, self.done_stage)

    def test_archived_request_passes(self):
        request = self._request(_link_vals())
        request.write({"archive": True})

        self._move(request, "maintenance.stage_5")

        self.assertEqual(request.stage_id, self.done_stage)

    def test_reactivated_in_the_same_write_is_checked(self):
        request = self._request(_link_vals())
        request.write({"archive": True})

        message = self._refusal(
            lambda: request.with_user(self.internal_user).write(
                {"archive": False, "stage_id": self.done_stage.id}
            )
        )

        self.assertIn("Saknar utfall: Frys (Kök).", message)
        self.assertNotEqual(request.stage_id, self.done_stage)

    def test_back_to_apartment_in_the_same_write_is_checked(self):
        request = self._request(_link_vals())
        request.write({"space_caption": "Tvättstuga"})

        message = self._refusal(
            lambda: request.with_user(self.internal_user).write(
                {"space_caption": "Lägenhet", "stage_id": self.done_stage.id}
            )
        )

        self.assertIn("Saknar utfall: Frys (Kök).", message)
        self.assertNotEqual(request.stage_id, self.done_stage)

    def test_new_request_in_done_needs_outcomes(self):
        message = self._refusal(
            lambda: _apartment_request(
                self.env,
                stage_id=self.done_stage.id,
                component_ids=[Command.create(_link_vals())],
            )
        )

        self.assertTrue(
            message.startswith(
                "Alla komponenter behöver ett utfall innan ärendet kan sparas som "
                f"{self.done_stage.name}. Spara det i en annan status"
            )
        )
        self.assertIn("Saknar utfall: Frys (Kök).", message)

    def test_also_when_the_stage_is_a_context_default(self):
        env = self.env(context=dict(self.env.context, default_stage_id=self.done_stage.id))

        message = self._refusal(
            lambda: _apartment_request(env, component_ids=[Command.create(_link_vals())])
        )

        self.assertIn(f"kan sparas som {self.done_stage.name}.", message)
        self.assertIn("Saknar utfall: Frys (Kök).", message)

    def test_new_request_in_done_with_outcomes_or_without_components(self):
        with_outcome = _apartment_request(
            self.env,
            stage_id=self.done_stage.id,
            component_ids=[Command.create(_link_vals(outcome="REPAIRED"))],
        )
        without_components = _apartment_request(self.env, stage_id=self.done_stage.id)

        self.assertEqual(with_outcome.stage_id, self.done_stage)
        self.assertEqual(without_components.stage_id, self.done_stage)

    def test_new_request_in_closed_without_a_resource_passes(self):
        request = _apartment_request(
            self.env,
            stage_id=self.closed_stage.id,
            component_ids=[Command.create(_link_vals())],
        )

        self.assertEqual(request.stage_id, self.closed_stage)
