"""Components an ärende concerns: the link model, its fields on the ärende,
the room grid's RPC and who may see and change the links."""

from unittest.mock import patch

from lxml import etree
from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from ..utils.test_utils import (
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_request,
    create_maintenance_team,
    create_rental_property,
    create_rental_property_option,
)

SERVICE_PATH = (
    "odoo.addons.onecore_maintenance_extension.models.maintenance.ComponentOneCoreService"
)
RENTAL_ID = "406-096-04-0101"


def _link_vals(component_id="comp-frys", label="Frys", **kwargs):
    vals = {
        "onecore_component_id": component_id,
        "installation_id": f"inst-{component_id}",
        "room_id": "room-kok",
        "room_name": "Kök",
        "room_sequence": 0,
        "label": label,
        "category_type": "EQUIPMENT",
    }
    vals.update(kwargs)
    return vals


def _apartment_request(env, **kwargs):
    rental_property = create_rental_property(env, rental_property_id=RENTAL_ID)
    request = create_maintenance_request(
        env, space_caption="Lägenhet", rental_property_id=rental_property.id, **kwargs
    )
    # Re-browse: create() returns a recordset whose context skips chatter
    # tracking on later writes
    return env["maintenance.request"].browse(request.id)


@tagged("onecore")
class TestRequestComponentLinks(TransactionCase):
    def setUp(self):
        super().setUp()
        self.request = _apartment_request(self.env)

    def test_component_is_linked_with_its_note(self):
        self.request.write(
            {"component_link_ids": [Command.create(_link_vals(note="Slutat frysa."))]}
        )

        link = self.request.component_link_ids
        self.assertEqual(len(link), 1)
        self.assertEqual(link.onecore_component_id, "comp-frys")
        self.assertEqual(link.label, "Frys")
        self.assertEqual(link.room_name, "Kök")
        self.assertEqual(link.note, "Slutat frysa.")

    def test_links_are_deleted_with_the_request(self):
        self.request.write({"component_link_ids": [Command.create(_link_vals())]})
        link = self.request.component_link_ids

        self.request.unlink()

        self.assertFalse(link.exists())

    def test_same_component_twice_on_one_request_is_refused(self):
        self.request.write({"component_link_ids": [Command.create(_link_vals())]})
        self.env.flush_all()

        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                self.request.write({"component_link_ids": [Command.create(_link_vals())]})
                self.env.flush_all()

    def test_same_component_on_two_requests_is_allowed(self):
        other = _apartment_request(self.env)

        self.request.write({"component_link_ids": [Command.create(_link_vals())]})
        other.write({"component_link_ids": [Command.create(_link_vals())]})
        self.env.flush_all()

        self.assertEqual(other.component_link_ids.onecore_component_id, "comp-frys")

    def test_uncheck_and_check_again_in_one_save(self):
        # The grid sends a delete and a create for the same component when
        # it is unchecked and checked again before saving
        self.request.write({"component_link_ids": [Command.create(_link_vals())]})
        self.env.flush_all()
        old_link = self.request.component_link_ids

        self.request.write(
            {
                "component_link_ids": [
                    Command.delete(old_link.id),
                    Command.create(_link_vals(note="Ny anteckning")),
                ]
            }
        )
        self.env.flush_all()

        self.assertFalse(old_link.exists())
        self.assertEqual(self.request.component_link_ids.note, "Ny anteckning")

    def _message_count(self):
        return self.env["mail.message"].search_count(
            [("model", "=", "maintenance.request"), ("res_id", "=", self.request.id)]
        )

    def test_changing_components_posts_no_chatter_note(self):
        messages_before = self._message_count()

        self.request.write({"component_link_ids": [Command.create(_link_vals())]})
        self.request.write(
            {
                "component_link_ids": [
                    Command.update(self.request.component_link_ids.id, {"note": "Läcker"})
                ]
            }
        )

        self.assertEqual(self._message_count(), messages_before)

    def test_rental_id_from_the_saved_rental_property(self):
        self.assertEqual(self.request.component_rental_id, RENTAL_ID)

    def test_rental_id_empty_without_rental_property(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.assertFalse(request.component_rental_id)

    def test_new_request_takes_rental_id_from_the_selected_search_hit(self):
        option = create_rental_property_option(self.env, name=RENTAL_ID)

        record = self.env["maintenance.request"].new(
            {"space_caption": "Lägenhet", "rental_property_option_id": option.id}
        )

        self.assertEqual(record.component_rental_id, RENTAL_ID)

    def test_choosing_another_rental_object_clears_the_components(self):
        first = create_rental_property_option(self.env, name=RENTAL_ID)
        second = create_rental_property_option(self.env, name="406-096-04-0102")
        record = self.env["maintenance.request"].new(
            {
                "space_caption": "Lägenhet",
                "rental_property_option_id": first.id,
                "component_link_ids": [Command.create(_link_vals())],
            }
        )
        self.assertEqual(len(record.component_link_ids), 1)

        record.rental_property_option_id = second
        record._onchange_rental_property_option_id()

        self.assertFalse(record.component_link_ids)
        self.assertEqual(record.component_rental_id, "406-096-04-0102")


@tagged("onecore")
class TestGetRoomComponents(TransactionCase):
    def setUp(self):
        super().setUp()
        self.result = {"ok": True, "rooms": [{"id": "room-kok", "name": "Kök"}]}

    def _call(self, user, rental_id=RENTAL_ID):
        with patch(SERVICE_PATH) as MockService:
            load = MockService.return_value.load_room_components
            load.return_value = self.result
            result = self.env["maintenance.request"].with_user(user).get_room_components(
                rental_id
            )
        return result, load

    def test_internal_user_gets_the_rooms(self):
        result, load = self._call(create_internal_user(self.env))

        self.assertEqual(result, self.result)
        load.assert_called_once_with(RENTAL_ID)

    def test_contractor_gets_rooms_of_their_teams_request(self):
        contractor = create_external_contractor_user(self.env)
        team = create_maintenance_team(self.env, member_ids=[Command.link(contractor.id)])
        _apartment_request(self.env, maintenance_team_id=team.id)

        result, load = self._call(contractor)

        self.assertEqual(result, self.result)
        load.assert_called_once_with(RENTAL_ID)

    def test_contractor_gets_nothing_for_another_rental_object(self):
        contractor = create_external_contractor_user(self.env)
        other_team = create_maintenance_team(self.env)
        _apartment_request(self.env, maintenance_team_id=other_team.id)

        result, load = self._call(contractor)

        self.assertEqual(result, {"ok": False, "rooms": []})
        load.assert_not_called()


@tagged("onecore")
class TestRequestComponentAccess(TransactionCase):
    """A link is visible and editable exactly when its ärende is; contractors
    can't change links once the ärende is in Utförd."""

    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.contractor = create_external_contractor_user(self.env)
        self.contractor_team = create_maintenance_team(
            self.env, member_ids=[Command.link(self.contractor.id)]
        )
        self.other_team = create_maintenance_team(self.env)

    def _request_with_link(self, team):
        request = _apartment_request(self.env, maintenance_team_id=team.id)
        request.write({"component_link_ids": [Command.create(_link_vals())]})
        return request

    def test_internal_user_can_add_change_and_remove_components(self):
        request = _apartment_request(self.env, maintenance_team_id=self.other_team.id)
        Link = self.env["maintenance.request.component"].with_user(self.internal_user)

        link = Link.create({"request_id": request.id, **_link_vals()})
        link.write({"note": "Läcker vatten"})
        self.assertEqual(link.note, "Läcker vatten")
        link.unlink()

        self.assertFalse(request.component_link_ids)

    def test_contractor_reads_components_on_their_teams_request(self):
        request = self._request_with_link(self.contractor_team)

        links = request.with_user(self.contractor).component_link_ids

        self.assertEqual(links.mapped("label"), ["Frys"])

    def test_contractor_reads_components_on_a_request_they_follow(self):
        request = self._request_with_link(self.other_team)
        request.message_subscribe(partner_ids=self.contractor.partner_id.ids)

        links = request.with_user(self.contractor).component_link_ids

        self.assertEqual(links.mapped("label"), ["Frys"])

    def test_contractor_cannot_read_components_on_other_requests(self):
        link = self._request_with_link(self.other_team).component_link_ids

        with self.assertRaises(AccessError):
            link.with_user(self.contractor).read(["label"])

    def _move_to_utford(self, request):
        # A resource first: an ärende can't be Utförd without one
        request = self.env["maintenance.request"].browse(request.id).with_user(
            self.internal_user
        )
        request.write({"user_id": self.internal_user.id})
        request.write({"stage_id": self.env.ref("maintenance.stage_5").id})

    def test_contractor_can_add_change_and_remove_components_on_their_teams_request(self):
        request = self._request_with_link(self.contractor_team)
        as_contractor = request.with_user(self.contractor)

        # The way the form saves: through the ärende
        as_contractor.write(
            {"component_link_ids": [Command.create(_link_vals("comp-spis", "Spis"))]}
        )
        spis = as_contractor.component_link_ids.filtered(lambda l: l.label == "Spis")
        spis.write({"note": "Plattorna blir inte varma"})
        self.assertEqual(spis.note, "Plattorna blir inte varma")
        as_contractor.component_link_ids.filtered(lambda l: l.label == "Frys").unlink()

        self.assertEqual(request.component_link_ids.mapped("label"), ["Spis"])

    def test_contractor_can_change_components_on_a_request_they_follow(self):
        request = self._request_with_link(self.other_team)
        request.message_subscribe(partner_ids=self.contractor.partner_id.ids)
        link = request.component_link_ids.with_user(self.contractor)

        link.write({"note": "Ändrad"})

        self.assertEqual(link.note, "Ändrad")

    def test_contractor_cannot_add_components_on_other_requests(self):
        request = self._request_with_link(self.other_team)
        Link = self.env["maintenance.request.component"].with_user(self.contractor)

        with self.assertRaises(AccessError):
            Link.create({"request_id": request.id, **_link_vals("comp-spis", "Spis")})

    def test_contractor_cannot_change_components_once_utford(self):
        request = self._request_with_link(self.contractor_team)
        self._move_to_utford(request)
        Link = self.env["maintenance.request.component"].with_user(self.contractor)
        link = request.component_link_ids.with_user(self.contractor)

        with self.assertRaises(AccessError):
            Link.create({"request_id": request.id, **_link_vals("comp-spis", "Spis")})
        with self.assertRaises(AccessError):
            link.write({"note": "Ändrad"})
        with self.assertRaises(AccessError):
            link.unlink()
        # Still readable
        self.assertEqual(link.label, "Frys")

    def test_internal_user_can_still_change_components_once_utford(self):
        request = self._request_with_link(self.contractor_team)
        self._move_to_utford(request)
        link = request.component_link_ids.with_user(self.internal_user)

        link.write({"note": "Bytt termostat"})

        self.assertEqual(link.note, "Bytt termostat")


@tagged("onecore")
class TestRequestComponentFormView(TransactionCase):
    def test_form_shows_grid_and_notes_read_only_for_restricted_contractors(self):
        view = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_form_extension"
        )
        arch = etree.fromstring(view.arch_db)

        nodes = arch.xpath('//field[@name="component_link_ids"]')
        self.assertEqual(
            sorted(node.get("widget") for node in nodes),
            ["component_notes", "room_components"],
        )
        for node in nodes:
            self.assertEqual(node.get("readonly"), "restricted_external")
            # Statically invisible would stop the lines from loading
            self.assertNotIn(node.get("invisible"), ("1", "True"))
        self.assertEqual(len(arch.xpath('//widget[@name="room_components_count"]')), 1)

    def test_form_view_still_renders(self):
        arch = etree.fromstring(
            self.env["maintenance.request"].get_view(view_type="form")["arch"]
        )

        self.assertEqual(len(arch.xpath('//field[@name="component_link_ids"]')), 2)
