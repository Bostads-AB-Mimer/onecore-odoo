"""Record management service for maintenance requests."""

import base64
import datetime
import logging
from odoo import fields
from ..utils.helpers import get_tenant_name, get_main_phone_number

_logger = logging.getLogger(__name__)


class RecordManagementService:
    """Service for handling all record creation and management operations."""

    def __init__(self, env):
        self.env = env

    def create_related_records(self, maintenance_request, vals):
        """Create all related records for a maintenance request."""
        self._save_property(maintenance_request, vals)
        self._save_building(maintenance_request, vals)
        self._save_staircase(maintenance_request, vals)
        self._save_rental_property(maintenance_request, vals)
        self._save_maintenance_unit(maintenance_request, vals)
        self._save_lease(maintenance_request, vals)
        self._save_tenant(maintenance_request, vals)
        self._save_parking_space(maintenance_request, vals)
        self._save_facility(maintenance_request, vals)

    def _save_property(self, maintenance_request, vals):
        """Save property data if present."""
        if not vals.get("property_option_id"):
            return

        property_option_record = self.env["maintenance.property.option"].search(
            [("id", "=", vals.get("property_option_id"))]
        )
        new_property_record = self.env["maintenance.property"].create(
            {
                "designation": property_option_record.designation,
                "code": property_option_record.code,
                "maintenance_request_id": maintenance_request.id,
            }
        )
        maintenance_request.write({"property_id": new_property_record.id})

    def _save_building(self, maintenance_request, vals):
        """Save building data if present."""
        if not vals.get("building_option_id"):
            return

        building_option_record = self.env["maintenance.building.option"].search(
            [("id", "=", vals.get("building_option_id"))]
        )
        new_building_record = self.env["maintenance.building"].create(
            {
                "name": building_option_record.name,
                "code": building_option_record.code,
                "building_type_name": building_option_record.building_type_name,
                "construction_year": building_option_record.construction_year,
                "renovation_year": building_option_record.renovation_year,
                "maintenance_request_id": maintenance_request.id,
            }
        )
        maintenance_request.write({"building_id": new_building_record.id})

    def _save_staircase(self, maintenance_request, vals):
        """Save staircase data if present."""
        if not vals.get("staircase_option_id"):
            return

        staircase_option_record = self.env["maintenance.staircase.option"].search(
            [("id", "=", vals.get("staircase_option_id"))]
        )
        new_staircase_record = self.env["maintenance.staircase"].create(
            {
                "staircase_id": staircase_option_record.staircase_id,
                "name": staircase_option_record.name,
                "code": staircase_option_record.code,
                "floor_plan": staircase_option_record.floor_plan,
                "accessible_by_elevator": staircase_option_record.accessible_by_elevator,
                "maintenance_request_id": maintenance_request.id,
            }
        )
        maintenance_request.write({"staircase_id": new_staircase_record.id})

    def _save_rental_property(self, maintenance_request, vals):
        """Save rental property data if present."""
        if not vals.get("rental_property_option_id"):
            return

        rental_property_option_record = self.env[
            "maintenance.rental.property.option"
        ].search([("id", "=", vals.get("rental_property_option_id"))])

        new_property_record = self.env["maintenance.rental.property"].create(
            {
                "name": rental_property_option_record.name,
                "rental_property_id": rental_property_option_record.name,
                "property_type": rental_property_option_record.property_type,
                "address": rental_property_option_record.address,
                "code": rental_property_option_record.code,
                "type": rental_property_option_record.type,
                "area": rental_property_option_record.area,
                "entrance": rental_property_option_record.entrance,
                "floor": rental_property_option_record.floor,
                "has_elevator": rental_property_option_record.has_elevator,
                "estate_code": rental_property_option_record.estate_code,
                "estate": rental_property_option_record.estate,
                "building_code": rental_property_option_record.building_code,
                "building": rental_property_option_record.building,
                "maintenance_request_id": maintenance_request.id,
            }
        )
        maintenance_request.write({"rental_property_id": new_property_record.id})

    def _save_maintenance_unit(self, maintenance_request, vals):
        """Save maintenance unit data if present."""
        if not vals.get("maintenance_unit_option_id"):
            return

        maintenance_unit_option_record = self.env[
            "maintenance.maintenance.unit.option"
        ].search([("id", "=", vals.get("maintenance_unit_option_id"))])

        new_maintenance_unit_record = self.env["maintenance.maintenance.unit"].create(
            {
                "name": maintenance_unit_option_record.name,
                "caption": maintenance_unit_option_record.caption,
                "type": maintenance_unit_option_record.type,
                "code": maintenance_unit_option_record.code,
                "maintenance_request_id": maintenance_request.id,
            }
        )
        maintenance_request.write(
            {"maintenance_unit_id": new_maintenance_unit_record.id}
        )

    def _save_lease(self, maintenance_request, vals):
        """Save lease data if present."""
        if not vals.get("lease_option_id"):
            return

        lease_option_record = self.env["maintenance.lease.option"].search(
            [("id", "=", vals.get("lease_option_id"))]
        )
        new_lease_record = self.env["maintenance.lease"].create(
            {
                "lease_id": lease_option_record.name,
                "name": lease_option_record.name,
                "lease_number": lease_option_record.lease_number,
                "lease_type": lease_option_record.lease_type,
                "lease_start_date": lease_option_record.lease_start_date,
                "lease_end_date": lease_option_record.lease_end_date,
                "contract_date": lease_option_record.contract_date,
                "approval_date": lease_option_record.approval_date,
                "maintenance_request_id": maintenance_request.id,
            }
        )
        maintenance_request.write({"lease_id": new_lease_record.id})

    def _save_tenant(self, maintenance_request, vals):
        """Save tenant data if present."""
        if not vals.get("tenant_option_id"):
            return

        tenant_option_record = self.env["maintenance.tenant.option"].search(
            [("id", "=", vals.get("tenant_option_id"))]
        )

        # Use the phone number and email from vals if they exist (modified in form),
        # otherwise use the option record's phone number/email
        phone_number_to_save = vals.get(
            "phone_number", tenant_option_record.phone_number
        )
        email_to_save = vals.get("email_address", tenant_option_record.email_address)

        new_tenant_record = self.env["maintenance.tenant"].create(
            {
                "name": tenant_option_record.name,
                "contact_code": tenant_option_record.contact_code,
                "contact_key": tenant_option_record.contact_key,
                "national_registration_number": tenant_option_record.national_registration_number,
                "email_address": email_to_save,
                "phone_number": phone_number_to_save,
                "is_tenant": tenant_option_record.is_tenant,
                "special_attention": tenant_option_record.special_attention,
                "maintenance_request_id": maintenance_request.id,
            }
        )
        maintenance_request.write({"tenant_id": new_tenant_record.id})

    def _save_parking_space(self, maintenance_request, vals):
        """Save parking space data if present."""
        if not vals.get("parking_space_option_id"):
            return

        parking_space_option_record = self.env[
            "maintenance.parking.space.option"
        ].search([("id", "=", vals.get("parking_space_option_id"))])

        new_parking_space_record = self.env["maintenance.parking.space"].create(
            {
                "name": parking_space_option_record.name,
                "code": parking_space_option_record.code,
                "type_name": parking_space_option_record.type_name,
                "type_code": parking_space_option_record.type_code,
                "number": parking_space_option_record.number,
                "property_code": parking_space_option_record.property_code,
                "property_name": parking_space_option_record.property_name,
                "address": parking_space_option_record.address,
                "postal_code": parking_space_option_record.postal_code,
                "city": parking_space_option_record.city,
                "maintenance_request_id": maintenance_request.id,
            }
        )
        maintenance_request.write({"parking_space_id": new_parking_space_record.id})

    def _save_facility(self, maintenance_request, vals):
        """Save facility data if present."""
        if not vals.get("facility_option_id"):
            return

        facility_option_record = self.env["maintenance.facility.option"].search(
            [("id", "=", vals.get("facility_option_id"))]
        )
        new_facility_record = self.env["maintenance.facility"].create(
            {
                "name": facility_option_record.name,
                "code": facility_option_record.code,
                "type_name": facility_option_record.type_name,
                "type_code": facility_option_record.type_code,
                "rental_type": facility_option_record.rental_type,
                "area": facility_option_record.area,
                "building_code": facility_option_record.building_code,
                "building_name": facility_option_record.building_name,
                "property_code": facility_option_record.property_code,
                "property_name": facility_option_record.property_name,
                "maintenance_request_id": maintenance_request.id,
            }
        )
        maintenance_request.write({"facility_id": new_facility_record.id})

    def handle_images(self, request, images):
        """Handle image attachments for maintenance request."""
        if not images:
            return

        for image in images:
            file_data = base64.b64decode(image["Base64String"])
            self.env["ir.attachment"].create(
                {
                    "name": image["Filename"],
                    "type": "binary",
                    "datas": base64.b64encode(file_data),
                    "res_model": "maintenance.request",
                    "res_id": request.id,
                    "mimetype": "application/octet-stream",
                }
            )

    def setup_team_assignment(self, request):
        """Auto-assign to team if equipment has a team."""
        if request.equipment_id and not request.maintenance_team_id:
            request.maintenance_team_id = request.equipment_id.maintenance_team_id

    def setup_close_date(self, request):
        """Handle close date logic based on stage."""
        if request.close_date and not request.stage_id.done:
            request.close_date = False
        elif not request.close_date and request.stage_id.done:
            request.close_date = self.env["fields"].Date.today()

    def handle_empty_tenant_logic(self, record):
        """Handle logic for empty tenants and recently added tenants."""
        if record.lease_name and record.create_date or not record.create_date:
            record.empty_tenant = False
        else:
            record.empty_tenant = True

        if record.recently_added_tenant and record.tenant_id:
            # Check if the tenant was created more than two weeks ago
            if (datetime.datetime.now() - record.tenant_id.create_date).days > 14:
                record.recently_added_tenant = False
        else:
            record.recently_added_tenant = False

        if record.rental_property_id and not record.lease_id:  # Empty tenant / lease
            self._create_missing_lease_and_tenant(record)

    def _create_missing_lease_and_tenant(self, record):
        """Create missing lease and tenant data from API."""
        data = self.env["onecore.api"].fetch_property_data(
            "rentalObjectId", record.rental_property_id.name
        )
        if not data:
            return

        for property_data in data:
            if not property_data["leases"] or len(property_data["leases"]) == 0:
                return  # No leases found in response.

            for lease in property_data["leases"]:
                new_lease_record = self._create_lease(lease, record)
                record.lease_id = new_lease_record.id

                if new_lease_record:
                    self._create_tenant(lease["tenants"], record)

    def _create_lease(self, lease, record):
        """Create a lease record from API data."""
        return self.env["maintenance.lease"].create(
            {
                "lease_id": lease["leaseId"],
                "name": lease["leaseId"],
                "lease_number": lease["leaseNumber"],
                "lease_type": lease["type"],
                "lease_start_date": lease["leaseStartDate"],
                "lease_end_date": lease["lastDebitDate"],
                "contract_date": lease["contractDate"],
                "approval_date": lease["approvalDate"],
            }
        )

    def _create_tenant(self, tenants, record):
        """Create tenant records from API data."""
        for tenant in tenants:
            name = get_tenant_name(tenant)
            phone_number = get_main_phone_number(tenant)

            recently_added_tenant_record = self.env["maintenance.tenant"].create(
                {
                    "name": name,
                    "contact_code": tenant["contactCode"],
                    "contact_key": tenant["contactKey"],
                    "national_registration_number": tenant[
                        "nationalRegistrationNumber"
                    ],
                    "email_address": tenant.get("emailAddress"),
                    "phone_number": phone_number,
                    "is_tenant": tenant["isTenant"],
                }
            )

            record.tenant_id = recently_added_tenant_record.id
            record.recently_added_tenant = True
            record.empty_tenant = False
