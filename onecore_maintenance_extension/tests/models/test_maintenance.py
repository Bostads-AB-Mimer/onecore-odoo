from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError
from datetime import date, timedelta

from lxml import etree

from ..utils.test_utils import (
    setup_faker,
    create_internal_user,
    create_maintenance_request,
    create_property_option,
    create_building_option,
    create_parking_space_option,
    create_property,
    create_building,
)
from ...models.utils.helpers import get_tenant_name, get_main_phone_number


class FakerMixin:
    """Mixin providing faker setup"""

    def _setup_faker(self):
        """Setup faker with Swedish locale and maintenance provider"""
        if not hasattr(self, "fake"):
            self.fake = setup_faker()


class StageTestMixin:
    """Mixin for maintenance stage lookups"""

    def _get_stage(self, stage_name):
        """Get maintenance stage by name"""
        return self.env["maintenance.stage"].search([("name", "=", stage_name)])

    def _setup_common_stages(self):
        """Setup commonly used stages"""
        self.stage_utford = self._get_stage("Utförd")
        self.stage_avslutad = self._get_stage("Avslutad")
        self.stage_vantar = self._get_stage("Väntar på handläggning")
        self.stage_tilldelad = self._get_stage("Resurs tilldelad")
        self.stage_paborjad = self._get_stage("Påbörjad")
        self.stage_vantar_varor = self._get_stage("Väntar på beställda varor")


@tagged("onecore")
class TestMaintenanceRequestDueDate(FakerMixin, TransactionCase):
    def setUp(self):
        super().setUp()
        self._setup_faker()

    def test_due_date_with_priority_and_request_date(self):
        """Due date should be request_date + priority_expanded days if start_date is not set."""
        request_date = date.today()
        priority_days = 5
        request = create_maintenance_request(
            self.env, request_date=request_date, priority_expanded=str(priority_days)
        )
        expected_due_date = request_date + timedelta(days=priority_days)
        self.assertEqual(request.due_date, expected_due_date)

    def test_due_date_with_priority_and_start_date(self):
        """Due date should be start_date + priority_expanded days if start_date is set."""
        request_date = date.today()
        start_date = request_date + timedelta(days=2)
        priority_days = 5
        request = create_maintenance_request(
            self.env,
            request_date=request_date,
            start_date=start_date,
            priority_expanded=str(priority_days),
        )
        expected_due_date = start_date + timedelta(days=priority_days)
        self.assertEqual(request.due_date, expected_due_date)

    def test_due_date_with_priority_6_months(self):
        """6 månader option should map to 183 days."""
        request_date = date.today()
        request = create_maintenance_request(
            self.env, request_date=request_date, priority_expanded="183"
        )
        self.assertEqual(request.due_date, request_date + timedelta(days=183))

    def test_due_date_with_priority_more_than_one_year(self):
        """mer än 1 år option should map to 365 days."""
        request_date = date.today()
        request = create_maintenance_request(
            self.env, request_date=request_date, priority_expanded="365"
        )
        self.assertEqual(request.due_date, request_date + timedelta(days=365))

    def test_manual_due_date_persists_on_write(self):
        """Manually overriding due_date after auto-fill should survive save."""
        request_date = date.today()
        request = create_maintenance_request(
            self.env, request_date=request_date, priority_expanded="42"
        )
        self.assertEqual(request.due_date, request_date + timedelta(days=42))

        manual_due_date = request_date + timedelta(days=30)
        request.write({"due_date": manual_due_date})
        request.invalidate_recordset()
        self.assertEqual(request.due_date, manual_due_date)

    def test_priority_change_recomputes_due_date(self):
        """Changing priority without touching due_date should refresh the deadline."""
        request_date = date.today()
        request = create_maintenance_request(
            self.env, request_date=request_date, priority_expanded="14"
        )
        self.assertEqual(request.due_date, request_date + timedelta(days=14))

        request.write({"priority_expanded": "42"})
        self.assertEqual(request.due_date, request_date + timedelta(days=42))

    def test_explicit_due_date_wins_over_recompute(self):
        """Writing priority and due_date in the same vals should persist the user's due_date."""
        request_date = date.today()
        request = create_maintenance_request(
            self.env, request_date=request_date, priority_expanded="14"
        )

        manual_due_date = request_date + timedelta(days=100)
        request.write(
            {"priority_expanded": "42", "due_date": manual_due_date}
        )
        request.invalidate_recordset()
        self.assertEqual(request.due_date, manual_due_date)

    def test_explicit_due_date_in_create_persists(self):
        """Creating with both priority and explicit due_date should keep the explicit value."""
        request_date = date.today()
        manual_due_date = request_date + timedelta(days=100)
        request = create_maintenance_request(
            self.env,
            request_date=request_date,
            priority_expanded="42",
            due_date=manual_due_date,
        )
        request.invalidate_recordset()
        self.assertEqual(request.due_date, manual_due_date)


@tagged("onecore")
class TestMaintenanceRequestFormState(TransactionCase):
    def setUp(self):
        super().setUp()
        self.property = create_property(self.env)
        self.property_option = create_property_option(self.env)
        self.building = create_building(self.env)
        self.building_option = create_building_option(self.env)

    def test_form_state_computed_from_space_caption(self):
        """Test that form_state is correctly computed when space_caption changes"""
        request = create_maintenance_request(self.env)

        # Test all form_state mappings by changing space_caption
        test_cases = [
            ("Bilplats", "parking-space"),
            ("Fastighet", "property"),
            ("Byggnad", "building"),
            ("Uppgång", "building"),
            ("Vind", "building"),
            ("Källare", "building"),
            ("Cykelförråd", "building"),
            ("Gården/Utomhus", "building"),
            ("Övrigt", "building"),
            ("Tvättstuga", "maintenance-unit"),
            ("Miljöbod", "maintenance-unit"),
            ("Lekplats", "maintenance-unit"),
            ("Lägenhet", "rental-property"),
            ("Lokal", "facility"),
        ]

        for space_caption, expected_form_state in test_cases:
            with self.subTest(space_caption=space_caption):
                request.write({"space_caption": space_caption})
                self.assertEqual(request.form_state, expected_form_state)

    def test_form_state_fallback_to_rental_property(self):
        """Test that form_state defaults to 'rental-property' for undefined space_caption"""
        request = create_maintenance_request(self.env, space_caption="Bilplats")

        # Set space_caption to False (no selection) to trigger fallback
        request.write({"space_caption": False})
        self.assertEqual(request.form_state, "rental-property")


@tagged("onecore")
class TestMaintenanceRequestUtilityMethods(FakerMixin, TransactionCase):
    def setUp(self):
        super().setUp()
        self._setup_faker()
        self.internal_user = create_internal_user(self.env)

    def test_get_tenant_name_with_first_last_name(self):
        """_get_tenant_name should construct name from firstName and lastName"""
        first_name = self.fake.first_name()
        last_name = self.fake.last_name()
        full_name = self.fake.tenant_full_name()

        tenant_data = {
            "firstName": first_name,
            "lastName": last_name,
            "fullName": full_name,
        }

        name = get_tenant_name(tenant_data)
        self.assertEqual(name, f"{first_name} {last_name}")

    def test_get_tenant_name_with_full_name_only(self):
        """_get_tenant_name should use fullName when firstName/lastName not available"""
        full_name = self.fake.tenant_full_name()
        tenant_data = {"fullName": full_name}

        name = get_tenant_name(tenant_data)
        self.assertEqual(name, full_name)

    def test_get_tenant_name_with_empty_data(self):
        """_get_tenant_name should return empty string for empty data"""
        tenant_data = {}

        name = get_tenant_name(tenant_data)
        self.assertEqual(name, "")

    def test_get_main_phone_number_finds_main_number(self):
        """_get_main_phone_number should find the phone number marked as main"""
        phone1 = self.fake.phone_number()
        phone2 = self.fake.phone_number()
        phone3 = self.fake.phone_number()

        tenant_data = {
            "phoneNumbers": [
                {"phoneNumber": phone1, "isMainNumber": 0},
                {"phoneNumber": phone2, "isMainNumber": 1},
                {"phoneNumber": phone3, "isMainNumber": 0},
            ]
        }

        phone = get_main_phone_number(tenant_data)
        self.assertEqual(phone, phone2)

    def test_get_main_phone_number_no_main_number(self):
        """_get_main_phone_number should return None when no main number exists"""
        phone1 = self.fake.phone_number()
        phone2 = self.fake.phone_number()

        tenant_data = {
            "phoneNumbers": [
                {"phoneNumber": phone1, "isMainNumber": 0},
                {"phoneNumber": phone2, "isMainNumber": 0},
            ]
        }

        phone = get_main_phone_number(tenant_data)
        self.assertIsNone(phone)

    def test_get_main_phone_number_empty_phone_numbers(self):
        """_get_main_phone_number should return None for empty phoneNumbers"""
        tenant_data = {"phoneNumbers": []}

        phone = get_main_phone_number(tenant_data)
        self.assertIsNone(phone)

    def test_get_main_phone_number_no_phone_numbers_key(self):
        """_get_main_phone_number should return None when phoneNumbers key missing"""
        tenant_data = {}

        phone = get_main_phone_number(tenant_data)
        self.assertIsNone(phone)

    def test_maintenance_team_domain_computation(self):
        """_compute_maintenance_team_domain should set correct user domain"""
        # Create maintenance team with specific members
        team_name = self.fake.company()
        team = self.env["maintenance.team"].create(
            {"name": team_name, "member_ids": [(6, 0, [self.internal_user.id])]}
        )

        request = create_maintenance_request(self.env, maintenance_team_id=team.id)

        # Should have correct domain
        expected_domain = [("id", "in", [self.internal_user.id])]
        self.assertEqual(request.maintenance_team_domain, expected_domain)


@tagged("onecore")
class TestMaintenanceRequestFormPropertyCode(TransactionCase):
    """MIM-2164: the property number (fastighetsnummer) is shown directly
    after the property name in every object group of the form."""

    def setUp(self):
        super().setUp()
        view = self.env.ref("maintenance.hr_equipment_request_view_form")
        arch = self.env["maintenance.request"].get_view(view.id, "form")["arch"]
        self.form = etree.fromstring(arch)

    def _group_fields(self, form_state):
        groups = self.form.xpath(
            f"//group[@invisible=\"form_state != '{form_state}'\"]"
        )
        self.assertEqual(len(groups), 1, form_state)
        return groups[0].xpath(".//field")

    def _assert_code_follows_name(self, form_state, name_field, code_field, invisible):
        fields = self._group_fields(form_state)
        names = [field.get("name") for field in fields]
        self.assertIn(code_field, names, form_state)
        index = names.index(code_field)
        self.assertGreater(index, 0, form_state)
        self.assertEqual(names[index - 1], name_field, form_state)
        code_node = fields[index]
        self.assertEqual(code_node.get("invisible"), invisible, form_state)
        self.assertEqual(code_node.get("string"), "Fastighetsnummer", form_state)

    def test_rental_property_shows_estate_code_after_estate(self):
        self._assert_code_follows_name(
            "rental-property", "estate", "estate_code", "not estate_code"
        )

    def test_maintenance_unit_shows_property_code_after_designation(self):
        self._assert_code_follows_name(
            "maintenance-unit",
            "property_designation",
            "property_code",
            "not property_code",
        )

    def test_property_shows_property_code_after_designation(self):
        self._assert_code_follows_name(
            "property", "property_designation", "property_code", "not property_code"
        )

    def test_building_shows_estate_code_after_estate(self):
        self._assert_code_follows_name(
            "building", "estate", "estate_code", "not estate_code"
        )

    def test_building_shows_building_property_code_after_property_name(self):
        self._assert_code_follows_name(
            "building",
            "building_property_name",
            "building_property_code",
            "estate or not building_property_code",
        )

    def test_parking_space_shows_property_code_after_property_name(self):
        self._assert_code_follows_name(
            "parking-space",
            "parking_space_property_name",
            "parking_space_property_code",
            "not parking_space_property_code",
        )

    def test_facility_shows_property_code_after_property_name(self):
        self._assert_code_follows_name(
            "facility",
            "facility_property_name",
            "facility_property_code",
            "not facility_property_code",
        )

    def test_property_code_set_when_property_selected(self):
        option = create_property_option(self.env, code="0123")
        record = self.env["maintenance.request"].new(
            {"space_caption": "Fastighet", "property_option_id": option.id}
        )
        record._onchange_property_option_id()
        self.assertEqual(record.property_code, "0123")

    def test_parking_space_property_code_set_when_parking_space_selected(self):
        option = create_parking_space_option(
            self.env, property_code="0456", property_name="Fastigheten"
        )
        record = self.env["maintenance.request"].new(
            {"space_caption": "Bilplats", "parking_space_option_id": option.id}
        )
        record._onchange_parking_space_option_id()
        self.assertEqual(record.parking_space_property_code, "0456")
