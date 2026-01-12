# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from ...onecore_api import core_api
import logging

_logger = logging.getLogger(__name__)


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
    condition = fields.Selection([
        ('NEW', 'Nyskick'),
        ('GOOD', 'Gott skick'),
        ('FAIR', 'Godtagbart skick'),
        ('POOR', 'Dåligt skick'),
        ('DAMAGED', 'Skadat'),
    ], string="Skick")
    specifications = fields.Text(string="Specifikationer")
    dimensions = fields.Char(string="Dimensioner")
    warranty_months = fields.Integer(string="Garanti (månader)")
    ncs_code = fields.Char(string="NCS-kod")
    additional_information = fields.Text(string="Ytterligare information")
    installation_date = fields.Date(string="Installationsdatum")

    # OneCore metadata
    room_name = fields.Char(string="Rum")
    onecore_component_id = fields.Char(string="OneCore Komponent-ID")

    # IDs for API submission
    room_id = fields.Char(string="Rum-ID")
    category_id = fields.Char(string="Kategori-ID")
    type_id = fields.Char(string="Typ-ID")
    subtype_id = fields.Char(string="Undertyp-ID")
    model_id = fields.Char(string="Modell-ID")
    installation_id = fields.Char(string="Installation-ID")

    # Economic fields
    price_at_purchase = fields.Float(string="Inköpspris")
    depreciation_price_at_purchase = fields.Float(string="Avskrivningspris")
    economic_lifespan = fields.Integer(string="Ekonomisk livslängd (månader)")

    # From subtype (read-only, display only)
    technical_lifespan = fields.Integer(string="Teknisk livslängd (månader)")
    replacement_interval = fields.Integer(string="Bytesintervall (månader)")

    # Computed current value
    current_value = fields.Float(
        string="Nuvarande värde",
        compute="_compute_current_value",
        store=False,
    )

    # Related field to access rooms from parent wizard
    available_rooms_json = fields.Text(
        related='wizard_id.available_rooms_json',
        string="Tillgängliga rum (JSON)"
    )

    @api.depends('price_at_purchase', 'economic_lifespan', 'installation_date')
    def _compute_current_value(self):
        """Compute current value using linear depreciation."""
        from dateutil.relativedelta import relativedelta
        today = fields.Date.today()
        for record in self:
            if record.price_at_purchase and record.economic_lifespan and record.installation_date:
                delta = relativedelta(today, record.installation_date)
                months_since = delta.years * 12 + delta.months
                if record.economic_lifespan > 0:
                    depreciation = (record.price_at_purchase / record.economic_lifespan) * months_since
                    record.current_value = max(0, record.price_at_purchase - depreciation)
                else:
                    record.current_value = record.price_at_purchase
            else:
                record.current_value = record.price_at_purchase or 0

    def action_save_component(self):
        """Save component changes to OneCore via PUT /components/{id} and /component-installations/{id}."""
        self.ensure_one()

        if not self.onecore_component_id:
            raise UserError("Kan inte spara: Komponenten saknar OneCore-ID.")

        api = core_api.CoreApi(self.env)

        # Validate required fields
        if not self.model_id:
            raise UserError("Kan inte spara: Komponenten saknar modell-ID.")

        # Room is required - user must select a room
        if not self.room_id:
            raise UserError("Du måste välja ett rum för komponenten.")

        # Build payload - only include fields with valid values
        component_payload = {
            "modelId": self.model_id,
            "condition": self.condition if self.condition else "NEW",
        }

        # Only include optional fields if they have values
        if self.serial_number:
            component_payload["serialNumber"] = self.serial_number
        if self.specifications:
            component_payload["specifications"] = self.specifications
        if self.additional_information:
            component_payload["additionalInformation"] = self.additional_information
        if self.warranty_months:
            component_payload["warrantyMonths"] = self.warranty_months
        if self.ncs_code:
            component_payload["ncsCode"] = self.ncs_code

        # Economic fields
        if self.price_at_purchase:
            component_payload["priceAtPurchase"] = self.price_at_purchase
        if self.depreciation_price_at_purchase:
            component_payload["depreciationPriceAtPurchase"] = self.depreciation_price_at_purchase
        if self.economic_lifespan:
            component_payload["economicLifespan"] = self.economic_lifespan

        _logger.info(f"Updating component {self.onecore_component_id} with payload: {component_payload}")

        try:
            # Update component fields
            api.update_component(self.onecore_component_id, component_payload)
            _logger.info(f"Successfully updated component {self.onecore_component_id}")

            # Update room/installation if installation_id exists (room_id is validated above)
            if self.installation_id:
                installation_payload = {
                    "componentId": self.onecore_component_id,
                    "spaceId": self.room_id,
                    "spaceType": "PropertyObject",  # PascalCase as per API spec
                }
                api.update_component_installation(self.installation_id, installation_payload)
                _logger.info(f"Successfully updated installation {self.installation_id} to room {self.room_id}")

        except Exception as e:
            _logger.error(f"Failed to update component: {e}")
            raise UserError(f"Kunde inte spara komponenten: {e}")

        # Reopen the parent wizard to show updated component list
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.component.wizard',
            'res_id': self.wizard_id.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_close_popup(self):
        """Close the inline form and reopen the parent wizard.

        Since Odoo's inline form dialogs close the entire modal stack,
        we reopen the parent wizard to return to its initial state.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.component.wizard',
            'res_id': self.wizard_id.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_uninstall_component(self):
        """Uninstall component by setting deinstallationDate."""
        self.ensure_one()

        if not self.installation_id:
            raise UserError("Kan inte avinstallera: Komponenten saknar installations-ID.")

        api = core_api.CoreApi(self.env)

        # Build payload with deinstallationDate
        from datetime import datetime, timezone
        installation_payload = {
            "componentId": self.onecore_component_id,
            "spaceId": self.room_id,
            "spaceType": "PropertyObject",
            "deinstallationDate": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        _logger.info(f"Uninstalling component {self.onecore_component_id} with payload: {installation_payload}")

        try:
            api.update_component_installation(self.installation_id, installation_payload)
            _logger.info(f"Successfully uninstalled component {self.onecore_component_id}")
        except Exception as e:
            _logger.error(f"Failed to uninstall component: {e}")
            raise UserError(f"Kunde inte avinstallera komponenten: {e}")

        # Save wizard reference before reload (reload deletes this record)
        wizard = self.wizard_id

        # Reload the component list from OneCore to reflect the uninstall
        wizard.reload_components()

        # Reopen the parent wizard to show updated component list
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.component.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
