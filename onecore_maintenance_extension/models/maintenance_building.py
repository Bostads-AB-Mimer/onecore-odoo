from odoo import models, fields


class OnecoreMaintenanceBuildingOption(models.Model):
    _name = "maintenance.building.option"
    _description = "building"
    _unaccent = True

    building_id = fields.Char(string="Byggnads ID", store=True)
    name = fields.Char("Namn", required=True)
    code = fields.Char("Kod")
    building_type_name = fields.Char("Byggnadstyp")
    construction_year = fields.Char("Byggår")
    renovation_year = fields.Char("Renoveringsår")
    # Property the building belongs to (OneCore building.property). Gives
    # building-level requests a property code — the join key for the
    # distrikt/kvartersvärdsområde lookup and the time report link.
    property_code = fields.Char("Fastighetsnummer")
    property_name = fields.Char("Fastighet")

    user_id = fields.Many2one("res.users", "User", default=lambda self: self.env.user)
    property_option_id = fields.Many2one(
        "maintenance.property.option",
        string="Property Option",
        ondelete="cascade"
    )


class OnecoreMaintenanceBuilding(models.Model):
    _name = "maintenance.building"
    _description = "Building"
    _unaccent = True

    building_id = fields.Char(string="Byggnads ID", store=True)
    name = fields.Char("Namn", required=True)
    code = fields.Char("Kod")
    building_type_name = fields.Char("Byggnadstyp")
    construction_year = fields.Char("Byggår")
    renovation_year = fields.Char("Renoveringsår")
    property_code = fields.Char("Fastighetsnummer")
    property_name = fields.Char("Fastighet")

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Maintenance Request", ondelete="cascade"
    )
