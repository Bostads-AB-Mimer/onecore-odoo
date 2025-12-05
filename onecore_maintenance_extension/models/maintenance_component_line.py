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
    typ = fields.Char(string="Typ")  # Legacy - keep for backward compatibility
    component = fields.Char(string="Komponent")  # Stores componentType from AI
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

    # AI metadata
    confidence = fields.Float(string="AI-säkerhet", digits=(3, 2))
    ai_suggested = fields.Boolean(string="AI-föreslagen", default=False)
    manually_reviewed = fields.Boolean(string="Manuellt granskad", default=False)
