from odoo import fields, models


class PropertyFieldsMixin(models.AbstractModel):
    """Mixin for property-related fields."""

    _name = "maintenance.property.fields.mixin"
    _description = "Property Fields Mixin"

    property_id = fields.Many2one(
        "maintenance.property", store=True, string="Fastighet"
    )
    property_designation = fields.Char(
        "Fastighetsbeteckning",
        related="property_id.designation",
        depends=["property_id"],
    )
    property_code = fields.Char(
        "Fastighetsnummer",
        related="property_id.code",
        depends=["property_id"],
    )
