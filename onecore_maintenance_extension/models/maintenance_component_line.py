# -*- coding: utf-8 -*-
from odoo import models, fields


class MaintenanceComponentLine(models.TransientModel):
    _name = "maintenance.component.line"
    _description = "Component Line"

    wizard_id = fields.Many2one(
        "maintenance.component.wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )

    # Image storage (transient)
    image = fields.Binary(string="Bild", attachment=False)
    additional_image = fields.Binary(string="Ytterligare bild", attachment=False)

    # AI-extracted component data (maps to API response)
    typ = fields.Char(string="Typ")  
    subtype = fields.Char(string="Undertyp")
    model = fields.Char(string="Modell")
    category = fields.Char(string="Kategori")
    manufacturer = fields.Char(string="Tillverkare")
    serial_number = fields.Char(string="Serienummer")
    estimated_age = fields.Char(string="Uppskattad ålder")
    condition = fields.Char(string="Skick")
    specifications = fields.Text(string="Specifikationer")
    dimensions = fields.Char(string="Dimensioner")
    warranty_months = fields.Integer(string="Garanti (månader)")
    ncs_code = fields.Char(string="NCS-kod")
    additional_information = fields.Text(string="Ytterligare information")
    installation_date = fields.Date(string="Installationsdatum")

    # OneCore metadata
    is_from_onecore = fields.Boolean(string="Från OneCore", default=False)
    room_name = fields.Char(string="Rum")
    onecore_component_id = fields.Char(string="OneCore Komponent-ID")

    # IDs for API submission
    room_id = fields.Char(string="Rum-ID")
    category_id = fields.Char(string="Kategori-ID")
    type_id = fields.Char(string="Typ-ID")
    subtype_id = fields.Char(string="Undertyp-ID")
