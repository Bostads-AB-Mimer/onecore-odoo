"""Component rows from the OneCore component ids that core sends with create
and write, as for the ärenden an inspection creates."""

from unittest.mock import Mock, PropertyMock, patch

from psycopg2.errors import SerializationFailure

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.onecore_maintenance_extension.models.services import (
    component_onecore_service,
)
from odoo.addons.onecore_maintenance_extension.models.services.component_onecore_service import (
    ComponentOneCoreService,
)

from ..utils.test_utils import (
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_team,
    create_rental_property,
)
from .services.test_component_onecore_service import _component, _room

RENTAL_ID = "406-096-04-0101"
MAINTENANCE_LOGGER = "odoo.addons.onecore_maintenance_extension.models.maintenance"


@tagged("onecore")
class TestComponentIntake(TransactionCase):
    def setUp(self):
        super().setUp()
        component_onecore_service._room_components_cache.clear()
        self.addCleanup(component_onecore_service._room_components_cache.clear)

        self.api = Mock()
        self.api.fetch_rooms.return_value = [
            _room("room-kok", "KÖK", 1),
            _room("room-bad", "Badrum", 2),
        ]
        self.api.parallel_get_json.return_value = [
            [
                _component("comp-frys", "Frys", "Frysskåp fristående", xpand_code="FRY01"),
                _component("comp-spis", "Spis", "Elspis"),
            ],
            [_component("comp-golv", "Golv", "Klinker", "SURFACE")],
        ]
        patcher = patch.object(
            ComponentOneCoreService, "api", new_callable=PropertyMock, return_value=self.api
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        # The integration user is an equipment manager; root is in the
        # contractor group
        self.manager = create_internal_user(self.env)
        self.rental_property = create_rental_property(
            self.env, rental_property_id=RENTAL_ID
        )

    def _vals(self, component_ids=None, **kwargs):
        """Values the way core creates an inspection's ärenden."""
        vals = {
            "name": "Besiktning 123 – Resursgrupp",
            "space_caption": "Lägenhet",
            "description": "<p>Skadade komponenter</p>",
            # A string id, as core sends it
            "rental_property_id": str(self.rental_property.id),
            "maintenance_request_category_id": self.env.ref(
                "onecore_maintenance_extension.category_1"
            ).id,
            "priority_expanded": "7",
        }
        if component_ids is not None:
            vals["onecore_component_ids"] = component_ids
        vals.update(kwargs)
        return vals

    def _create(self, component_ids=None, **kwargs):
        requests = self.env["maintenance.request"].with_user(self.manager).create(
            self._vals(component_ids, **kwargs)
        )
        # Re-browse: create() returns a recordset whose context skips chatter
        # tracking on later writes
        return self.env["maintenance.request"].with_user(self.manager).browse(requests.id)

    def _notes(self, request):
        return self.env["mail.message"].search(
            [
                ("model", "=", "maintenance.request"),
                ("res_id", "=", request.id),
                ("body", "ilike", "kunde inte kopplas"),
            ]
        )

    def _linked(self, request):
        return sorted(request.component_ids.mapped("onecore_component_id"))

    def test_create_links_the_components_with_the_grids_values(self):
        request = self._create(["comp-frys", "comp-golv"])

        self.assertEqual(
            [
                (
                    row.onecore_component_id,
                    row.installation_id,
                    row.rental_id,
                    row.space_id,
                    row.space_name,
                    row.space_sequence,
                    row.component_name,
                    row.subtype_name,
                    row.subtype_xpand_code,
                    row.category_type,
                )
                for row in request.component_ids.sorted("space_sequence")
            ],
            [
                (
                    "comp-frys", "inst-comp-frys", RENTAL_ID, "room-kok", "Kök", 0,
                    "Frys", "Frysskåp fristående", "FRY01", "EQUIPMENT",
                ),
                (
                    "comp-golv", "inst-comp-golv", RENTAL_ID, "room-bad", "Badrum", 1,
                    "Golv", "Klinker", False, "SURFACE",
                ),
            ],
        )
        self.assertFalse(self._notes(request))

    def test_resubmit_adds_only_the_new_components(self):
        request = self._create(["comp-frys", "comp-spis"])

        # Core sends the full list every time
        request.write(
            {
                "description": "<p>Skadade komponenter, nu tre</p>",
                "onecore_component_ids": ["comp-frys", "comp-spis", "comp-golv"],
            }
        )

        self.assertEqual(self._linked(request), ["comp-frys", "comp-golv", "comp-spis"])
        self.assertFalse(self._notes(request))

    def test_resubmit_with_everything_linked_asks_onecore_nothing(self):
        request = self._create(["comp-frys", "comp-spis"])
        component_onecore_service._room_components_cache.clear()
        self.api.reset_mock()

        request.write({"onecore_component_ids": ["comp-spis", "comp-frys"]})

        self.assertEqual(self._linked(request), ["comp-frys", "comp-spis"])
        self.api.fetch_rooms.assert_not_called()

    def test_resubmit_never_removes_rows(self):
        request = self._create(["comp-frys", "comp-spis"])
        request.write(
            {
                "component_ids": [
                    Command.create(
                        {
                            "onecore_component_id": "comp-golv",
                            "component_name": "Golv",
                            "rental_id": RENTAL_ID,
                            "note": "Spricka vid tröskeln",
                        }
                    )
                ]
            }
        )

        # Fewer ids than before, and not the one chosen in the grid
        request.write(
            {"description": "<p>Bara frysen</p>", "onecore_component_ids": ["comp-frys"]}
        )

        self.assertEqual(self._linked(request), ["comp-frys", "comp-golv", "comp-spis"])
        golv = request.component_ids.filtered(
            lambda row: row.onecore_component_id == "comp-golv"
        )
        self.assertEqual(golv.note, "Spricka vid tröskeln")

    def test_component_chosen_in_the_grid_is_not_linked_twice(self):
        request = self._create()
        request.write(
            {
                "component_ids": [
                    Command.create(
                        {
                            "onecore_component_id": "comp-frys",
                            "component_name": "Frys",
                            "rental_id": RENTAL_ID,
                        }
                    )
                ]
            }
        )
        self.env.flush_all()

        request.write({"onecore_component_ids": ["comp-frys", "comp-spis"]})
        self.env.flush_all()

        self.assertEqual(self._linked(request), ["comp-frys", "comp-spis"])

    def test_grid_and_component_ids_in_one_write_link_once(self):
        request = self._create()

        request.write(
            {
                "component_ids": [
                    Command.create(
                        {
                            "onecore_component_id": "comp-frys",
                            "component_name": "Frys",
                            "rental_id": RENTAL_ID,
                        }
                    )
                ],
                "onecore_component_ids": ["comp-frys"],
            }
        )
        self.env.flush_all()

        self.assertEqual(self._linked(request), ["comp-frys"])

    def test_component_linked_by_a_concurrent_transaction_is_skipped(self):
        request = self._create()
        # This transaction has read the rows: none yet
        self.assertFalse(request.component_ids)
        # Meanwhile another transaction links comp-frys
        self.env.cr.execute(
            "INSERT INTO maintenance_request_component"
            " (maintenance_request_id, onecore_component_id, component_name)"
            " VALUES (%s, 'comp-frys', 'Frys från en annan transaktion')",
            [request.id],
        )

        request.write({"onecore_component_ids": ["comp-frys", "comp-spis"]})

        request.invalidate_recordset(["component_ids"])
        self.assertEqual(self._linked(request), ["comp-frys", "comp-spis"])
        frys = request.component_ids.filtered(
            lambda row: row.onecore_component_id == "comp-frys"
        )
        self.assertEqual(frys.component_name, "Frys från en annan transaktion")

    def test_a_database_error_during_the_lookup_is_raised_for_a_retry(self):
        # E.g. a serialization failure when the OneCore token is refreshed:
        # Odoo rolls back and retries the whole call
        self.api.fetch_rooms.side_effect = SerializationFailure(
            "could not serialize access due to concurrent update"
        )

        with self.assertRaises(SerializationFailure):
            self._create(["comp-frys"])

    def test_unknown_and_uninstalled_components_get_a_note(self):
        removed = _component("comp-gammal", "Spis", "Elspis")
        removed["componentInstallations"][0]["deinstallationDate"] = "2025-01-01"
        self.api.parallel_get_json.return_value = [
            [_component("comp-frys", "Frys", "Frysskåp"), removed],
            [],
        ]

        with self.assertLogs(MAINTENANCE_LOGGER, "WARNING") as logs:
            request = self._create(["comp-frys", "comp-okand", "comp-gammal"])

        self.assertEqual(self._linked(request), ["comp-frys"])
        note = self._notes(request)
        self.assertEqual(len(note), 1)
        self.assertIn(
            "2 komponenter hittades inte i OneCore och kunde inte kopplas till ärendet. "
            "Välj rätt komponenter under Rum och komponenter.",
            note.body,
        )
        self.assertIn("not found in OneCore", "\n".join(logs.output))

    def test_components_in_a_room_that_failed_to_load_get_their_own_note(self):
        self.api.parallel_get_json.return_value = [
            [_component("comp-frys", "Frys", "Frysskåp")],
            # Badrum failed to load
            None,
        ]

        with self.assertLogs(MAINTENANCE_LOGGER, "WARNING") as logs:
            request = self._create(["comp-frys", "comp-golv"])

        self.assertEqual(self._linked(request), ["comp-frys"])
        self.assertIn(
            "1 komponent kunde inte kopplas till ärendet eftersom alla rum inte kunde "
            "hämtas från OneCore.",
            self._notes(request).body,
        )
        self.assertIn("some rooms failed to load", "\n".join(logs.output))

    def test_onecore_down_still_creates_the_request_with_a_note(self):
        self.api.fetch_rooms.side_effect = Exception("503 Service Unavailable")

        request = self._create(["comp-frys", "comp-spis"])

        self.assertTrue(request.exists())
        self.assertFalse(request.component_ids)
        note = self._notes(request).body
        self.assertIn(
            "2 komponenter kunde inte kopplas till ärendet eftersom OneCore inte svarade. "
            "Försök igen senare under Rum och komponenter.",
            note,
        )

    def test_onecore_down_on_resubmit_still_saves_the_description(self):
        request = self._create()
        self.api.fetch_rooms.side_effect = Exception("503 Service Unavailable")

        request.write(
            {
                "description": "<p>Ny beskrivning</p>",
                "onecore_component_ids": ["comp-frys"],
            }
        )

        self.assertIn("Ny beskrivning", request.description)
        self.assertFalse(request.component_ids)
        self.assertEqual(len(self._notes(request)), 1)

    def test_request_without_rental_object_gets_a_note(self):
        request = self._create(["comp-frys"], rental_property_id=False)

        self.assertFalse(request.component_ids)
        self.assertIn(
            "1 komponent kunde inte kopplas till ärendet eftersom det saknar hyresobjekt.",
            self._notes(request).body,
        )
        self.api.fetch_rooms.assert_not_called()

    def test_values_that_are_not_component_ids_are_ignored(self):
        request = self._create([None, 5, "", "comp-frys", "comp-frys", {"id": "comp-spis"}])

        self.assertEqual(self._linked(request), ["comp-frys"])
        self.assertFalse(self._notes(request))

    def test_a_value_that_is_not_a_list_is_ignored(self):
        request = self._create("comp-frys")
        request.write({"onecore_component_ids": False})

        self.assertFalse(request.component_ids)
        self.assertFalse(self._notes(request))
        self.api.fetch_rooms.assert_not_called()

    def test_no_or_empty_component_ids_ask_onecore_nothing(self):
        request = self._create([])
        request.write({"description": "<p>Ändrad beskrivning</p>"})
        request.write({"onecore_component_ids": []})

        self.assertFalse(request.component_ids)
        self.api.fetch_rooms.assert_not_called()

    def test_the_note_notifies_no_one(self):
        request = self._create()
        watcher = create_internal_user(self.env)
        request.message_subscribe(
            partner_ids=watcher.partner_id.ids,
            subtype_ids=self.env.ref("mail.mt_note").ids,
        )
        # The watcher does get ordinary notes
        control = request.message_post(body="Kontroll", subtype_xmlid="mail.mt_note")
        self.assertIn(watcher.partner_id, control.notification_ids.res_partner_id)

        request.write({"onecore_component_ids": ["comp-okand"]})

        note = self._notes(request)
        self.assertEqual(len(note), 1)
        self.assertIn("1 komponent hittades inte i OneCore", note.body)
        self.assertEqual(note.subtype_id, self.env.ref("mail.mt_note"))
        self.assertFalse(
            self.env["mail.notification"].search([("mail_message_id", "=", note.id)])
        )

    def test_create_of_several_requests_links_each_its_own_components(self):
        requests = self.env["maintenance.request"].with_user(self.manager).create(
            [
                self._vals(name="Besiktning 123 – Utan komponenter"),
                self._vals(["comp-frys"], name="Besiktning 123 – Kök"),
                self._vals(["comp-golv", "comp-spis"], name="Besiktning 123 – Golv"),
            ]
        )

        self.assertEqual(
            [self._linked(request) for request in requests],
            [[], ["comp-frys"], ["comp-golv", "comp-spis"]],
        )

    def test_write_on_several_requests_links_the_components_on_each(self):
        first = self._create(["comp-frys"])
        second = self._create()

        (first | second).write({"onecore_component_ids": ["comp-frys", "comp-spis"]})

        self.assertEqual(self._linked(first), ["comp-frys", "comp-spis"])
        self.assertEqual(self._linked(second), ["comp-frys", "comp-spis"])

    def _contractor_request(self):
        contractor = create_external_contractor_user(self.env)
        team = create_maintenance_team(self.env, member_ids=[Command.link(contractor.id)])
        return contractor, self._create(maintenance_team_id=team.id)

    def test_contractor_adds_components_to_their_teams_request(self):
        contractor, request = self._contractor_request()

        request.with_user(contractor).write({"onecore_component_ids": ["comp-frys"]})

        self.assertEqual(self._linked(request), ["comp-frys"])

    def test_contractor_cannot_add_components_once_utford(self):
        contractor, request = self._contractor_request()
        # A resource first: an ärende can't be Utförd without one
        request.write({"user_id": self.manager.id})
        request.write({"stage_id": self.env.ref("maintenance.stage_5").id})

        with self.assertRaises(AccessError) as error:
            request.with_user(contractor).write({"onecore_component_ids": ["comp-frys"]})

        # The guard on the component rows, not a record rule
        self.assertIn("Entreprenörer kan inte ändra komponenter", str(error.exception))
        self.assertFalse(request.component_ids)
