# -*- coding: utf-8 -*-
"""MIM-1921: the laundry room preselected on a request must be the one that
serves the tenant's apartment, never just the property's first one."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from unittest.mock import Mock

from ...utils.test_utils import (
    setup_faker,
    create_test_user,
    create_rental_property_option,
    create_maintenance_unit_option,
    create_lease_option,
)
from ....models.handlers.rental_property_handler import RentalPropertyHandler
from ....models.services.form_field_service import FormFieldService


def _new_request(env, **values):
    """An UNSAVED request, like the one the form's onchange hands the handler.

    The option fields are store=False and write() strips them, so on a saved
    record every preselection would be silently dropped — the real form never
    runs a search on a saved record (the search bar is hidden once created).
    """
    fake = setup_faker()
    return env["maintenance.request"].new(
        {
            "name": fake.maintenance_request_name(),
            "maintenance_request_category_id": env.ref(
                "onecore_maintenance_extension.category_1"
            ).id,
            "space_caption": "Tvättstuga",
            "priority_expanded": "7",
            **values,
        }
    )


def _unit(unit_id, code, serves=False):
    """A maintenance unit as fetch_form_data delivers it (OneCore id, flag)."""
    return {
        "id": unit_id,
        "code": code,
        "caption": f"TVÄTTSTUGA {code}",
        "type": "Tvättstuga",
        "serves_rental_object": serves,
    }


def _residence(rental_id, property_code="705"):
    return {
        "code": rental_id,
        "name": f"Adress {rental_id}",
        "type": {"name": "Lägenhet"},
        "areaSize": 60,
        "entrance": "A",
        "accessibility": {"elevator": False},
        "property": {"code": property_code, "name": "Fastighet"},
        "building": {"code": "705-010", "name": "Byggnad"},
        "rentalInformation": {"rentalId": rental_id},
    }


def _lease(rental_id, lease_id="L1", status=0):
    """status: 0 = Current, 1 = Upcoming (LEASE_STATUS_LABELS codes)."""
    return {
        "leaseId": lease_id,
        "leaseNumber": "01",
        "rentalPropertyId": rental_id,
        "type": "Bostadskontrakt",
        "leaseStartDate": "2020-01-01",
        "leaseEndDate": None,
        "lastDebitDate": None,
        "contractDate": "2019-12-01",
        "approvalDate": "2019-12-01",
        "status": status,
        "tenants": [],
    }


@tagged("onecore")
class TestRentalPropertyHandlerMaintenanceUnitPreselection(TransactionCase):
    def setUp(self):
        super().setUp()
        self.request = _new_request(self.env)
        self.handler = RentalPropertyHandler(self.request, Mock())

    def _run(self, work_order_data):
        self.handler.update_form_options(work_order_data)
        self.handler._set_form_selections("rentalObjectId", "705-010-04-0101")

    def test_preselects_serving_unit_not_first(self):
        """Eight laundry rooms on the property, the third serves the apartment."""
        units = [_unit(9000 + i, f"705T0{i}") for i in range(1, 9)]
        units[2]["serves_rental_object"] = True

        self._run(
            [
                {
                    "lease": _lease("705-010-04-0101"),
                    "rental_id": "705-010-04-0101",
                    "rental_property": _residence("705-010-04-0101"),
                    "maintenance_units": units,
                }
            ]
        )

        selected = self.request.maintenance_unit_option_id
        self.assertEqual(selected.code, "705T03")
        self.assertTrue(selected.serves_rental_object)
        # Copied onto the request by the same call
        self.assertEqual(self.request.maintenance_unit_code, "705T03")
        self.assertEqual(self.request.maintenance_unit_caption, "TVÄTTSTUGA 705T03")
        # All eight are still offered in the dropdown
        options = self.env["maintenance.maintenance.unit.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        self.assertEqual(len(options), 8)
        self.assertEqual(
            options.filtered("serves_rental_object").mapped("code"), ["705T03"]
        )

    def test_no_serving_unit_preselects_nothing(self):
        """No baxyk relation (Håkantorpsgatan): list shown, nothing preselected."""
        units = [_unit(9000 + i, f"216T0{i}") for i in range(1, 4)]

        self._run(
            [
                {
                    "lease": _lease("216-040-03-0101"),
                    "rental_id": "216-040-03-0101",
                    "rental_property": _residence("216-040-03-0101", "216"),
                    "maintenance_units": units,
                }
            ]
        )

        self.assertFalse(self.request.maintenance_unit_option_id)
        self.assertFalse(self.request.maintenance_unit_code)
        self.assertEqual(
            self.env["maintenance.maintenance.unit.option"].search_count(
                [("user_id", "=", self.env.user.id)]
            ),
            3,
        )

    def test_stale_unit_from_previous_search_is_cleared(self):
        """Search 1 preselects a unit; search 2 has none -> fields are cleared."""
        stale = create_maintenance_unit_option(self.env, code="OLD", caption="OLD")
        self.request.maintenance_unit_option_id = stale
        FormFieldService(self.env).update_maintenance_unit_fields(self.request)
        self.assertEqual(self.request.maintenance_unit_code, "OLD")
        self.handler._delete_options()

        self._run(
            [
                {
                    "lease": _lease("216-040-03-0101"),
                    "rental_id": "216-040-03-0101",
                    "rental_property": _residence("216-040-03-0101", "216"),
                    "maintenance_units": [_unit(9001, "216T01")],
                }
            ]
        )

        self.assertFalse(self.request.maintenance_unit_option_id)
        self.assertFalse(self.request.maintenance_unit_code)
        self.assertFalse(self.request.maintenance_unit_caption)

    def test_unit_follows_the_active_lease_not_the_first_item(self):
        """Two contracts on different objects, the CURRENT one listed second:
        the unit must belong to the current lease's apartment."""
        upcoming_units = [_unit(9101, "B-T01", serves=True)]
        current_units = [_unit(9201, "A-T01"), _unit(9202, "A-T02", serves=True)]

        self._run(
            [
                {
                    "lease": _lease("B", lease_id="LB", status=1),
                    "rental_id": "B",
                    "rental_property": _residence("B"),
                    "maintenance_units": upcoming_units,
                },
                {
                    "lease": _lease("A", lease_id="LA", status=0),
                    "rental_id": "A",
                    "rental_property": _residence("A"),
                    "maintenance_units": current_units,
                },
            ]
        )

        self.assertEqual(self.request.lease_option_id.lease_id, "LA")
        self.assertEqual(self.request.rental_property_option_id.rental_id, "A")
        self.assertEqual(self.request.maintenance_unit_option_id.code, "A-T02")

    def test_renewed_contract_lists_units_once(self):
        """Two lease items on the same object must not duplicate the dropdown."""
        units = [_unit(9000 + i, f"705T0{i}", serves=(i == 3)) for i in range(1, 9)]
        item = {
            "rental_id": "705-010-04-0101",
            "rental_property": _residence("705-010-04-0101"),
            "maintenance_units": units,
        }

        self._run(
            [
                {**item, "lease": _lease("705-010-04-0101", lease_id="OLD", status=0)},
                {**item, "lease": _lease("705-010-04-0101", lease_id="NEW", status=1)},
            ]
        )

        options = self.env["maintenance.maintenance.unit.option"].search(
            [("user_id", "=", self.env.user.id)]
        )
        self.assertEqual(len(options), 8)
        self.assertEqual(self.request.maintenance_unit_option_id.code, "705T03")

    def test_missing_flag_in_payload_is_treated_as_not_serving(self):
        """Older payload shape without the flag must not crash or preselect."""
        unit = _unit(9001, "705T01")
        del unit["serves_rental_object"]

        self._run(
            [
                {
                    "lease": _lease("705-010-04-0101"),
                    "rental_id": "705-010-04-0101",
                    "rental_property": _residence("705-010-04-0101"),
                    "maintenance_units": [unit],
                }
            ]
        )

        self.assertFalse(self.request.maintenance_unit_option_id)


@tagged("onecore")
class TestMaintenanceUnitDropdownVisibleWithoutPreselection(TransactionCase):
    """With nothing preselected the user must still be able to pick: the form
    used to hide maintenance_unit_option_id whenever it was empty."""

    def test_option_fields_are_shown_after_an_object_search(self):
        from lxml import etree

        arch = self.env["maintenance.request"].get_view(view_type="form")["arch"]
        nodes = etree.fromstring(arch).xpath(
            "//field[@name='maintenance_unit_option_id']"
        )
        self.assertEqual(len(nodes), 3)
        for node in nodes:
            invisible = node.get("invisible") or ""
            self.assertFalse(
                invisible.startswith("not maintenance_unit_option_id"),
                f"dropdown hidden when empty: {invisible}",
            )
            self.assertIn("rental_property_option_id", invisible)


@tagged("onecore")
class TestSwitchingRentalPropertyReselectsUnit(TransactionCase):
    """A tenant with two contracts: switching object in the form must switch
    the laundry room too, but a manual pick on the same object survives."""

    def setUp(self):
        super().setUp()
        self.request = _new_request(self.env)
        self.service = FormFieldService(self.env)

        self.apartment_a = create_rental_property_option(self.env, name="A")
        self.apartment_b = create_rental_property_option(self.env, name="B")
        self.unit_a = create_maintenance_unit_option(
            self.env,
            code="A-SERVING",
            rental_property_option_id=self.apartment_a.id,
            serves_rental_object=True,
        )
        self.unit_a_other = create_maintenance_unit_option(
            self.env, code="A-OTHER", rental_property_option_id=self.apartment_a.id
        )
        self.unit_b = create_maintenance_unit_option(
            self.env,
            code="B-SERVING",
            rental_property_option_id=self.apartment_b.id,
            serves_rental_object=True,
        )

    def test_switching_object_switches_unit(self):
        self.request.rental_property_option_id = self.apartment_a
        self.service.update_rental_property_fields(self.request)
        self.assertEqual(self.request.maintenance_unit_option_id, self.unit_a)

        self.request.rental_property_option_id = self.apartment_b
        self.service.update_rental_property_fields(self.request)
        self.assertEqual(self.request.maintenance_unit_option_id, self.unit_b)
        self.assertEqual(self.request.maintenance_unit_code, "B-SERVING")

    def test_manual_pick_on_same_object_is_kept(self):
        self.request.rental_property_option_id = self.apartment_a
        self.request.maintenance_unit_option_id = self.unit_a_other

        self.service.update_rental_property_fields(self.request)

        self.assertEqual(self.request.maintenance_unit_option_id, self.unit_a_other)

    def test_switching_to_object_without_serving_unit_clears(self):
        apartment_c = create_rental_property_option(self.env, name="C")
        self.request.rental_property_option_id = self.apartment_a
        self.service.update_rental_property_fields(self.request)

        self.request.rental_property_option_id = apartment_c
        self.service.update_rental_property_fields(self.request)

        self.assertFalse(self.request.maintenance_unit_option_id)
        self.assertFalse(self.request.maintenance_unit_code)

    def test_clearing_object_clears_unit(self):
        self.request.rental_property_option_id = self.apartment_a
        self.service.update_rental_property_fields(self.request)
        self.assertEqual(self.request.maintenance_unit_option_id, self.unit_a)

        self.request.rental_property_option_id = False
        self.service.update_rental_property_fields(self.request)

        self.assertFalse(self.request.maintenance_unit_option_id)
        self.assertFalse(self.request.maintenance_unit_code)

    def test_switching_lease_switches_object_and_unit(self):
        """The lease onchange moves the object; the unit must move with it,
        because the object's own onchange has already run in that cascade."""
        lease_a = create_lease_option(
            self.env, rental_property_option_id=self.apartment_a.id
        )
        lease_b = create_lease_option(
            self.env, rental_property_option_id=self.apartment_b.id
        )
        self.request.lease_option_id = lease_a
        self.service.update_lease_fields(self.request)
        self.assertEqual(self.request.rental_property_option_id, self.apartment_a)
        self.assertEqual(self.request.maintenance_unit_option_id, self.unit_a)

        self.request.lease_option_id = lease_b
        self.service.update_lease_fields(self.request)

        self.assertEqual(self.request.rental_property_option_id, self.apartment_b)
        self.assertEqual(self.request.maintenance_unit_option_id, self.unit_b)

    def test_other_users_options_are_ignored(self):
        """Options are per user; a colleague's serving unit must not leak in."""
        other = create_test_user(self.env)
        create_maintenance_unit_option(
            self.env,
            user_id=other.id,
            code="OTHER-USER",
            rental_property_option_id=self.apartment_b.id,
            serves_rental_object=True,
        )
        self.unit_b.unlink()

        self.request.rental_property_option_id = self.apartment_b
        self.service.select_serving_maintenance_unit(self.request)

        self.assertFalse(self.request.maintenance_unit_option_id)
