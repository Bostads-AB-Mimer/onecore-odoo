from odoo import fields, models


class FacilityFieldsMixin(models.AbstractModel):
    """Mixin for facility-related fields."""

    _name = "maintenance.facility.fields.mixin"
    _description = "Facility Fields Mixin"

    facility_id = fields.Many2one(
        "maintenance.facility", string="Facility ID", store=True
    )
    facility_name = fields.Char(
        "Lokal Namn", related="facility_id.name", depends=["facility_id"]
    )
    facility_code = fields.Char(
        "Lokal Kod", related="facility_id.code", depends=["facility_id"]
    )
    facility_type_name = fields.Char(
        "Lokaltyp", related="facility_id.type_name", depends=["facility_id"]
    )
    facility_type_code = fields.Char(
        "Lokaltypskod", related="facility_id.type_code", depends=["facility_id"]
    )
    facility_rental_type = fields.Char(
        "Hyrestyp", related="facility_id.rental_type", depends=["facility_id"]
    )
    facility_area = fields.Char(
        "Yta", related="facility_id.area", depends=["facility_id"]
    )
    facility_building_code = fields.Char(
        "Byggnadskod", related="facility_id.building_code", depends=["facility_id"]
    )
    facility_building_name = fields.Char(
        "Byggnad", related="facility_id.building_name", depends=["facility_id"]
    )
    facility_property_code = fields.Char(
        "Fastighetskod", related="facility_id.property_code", depends=["facility_id"]
    )
    facility_property_name = fields.Char(
        "Fastighet", related="facility_id.property_name", depends=["facility_id"]
    )
