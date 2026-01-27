# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timezone

from odoo import models, fields, api
from odoo.exceptions import UserError

from ...onecore_api import core_api
from .services.component_onecore_service import (
    ComponentOneCoreService,
    PROPERTY_OBJECT_SPACE_TYPE,
)
from .utils.depreciation import compute_linear_depreciation

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

    # All image URLs from OneCore as JSON array
    image_urls_json = fields.Text(string="Bild-URLer (JSON)", default='[]')

    # Computed field to check if there are any images
    has_images = fields.Boolean(
        string="Has Images",
        compute="_compute_has_images",
        store=False,
    )

    # New image upload fields (for adding images during update)
    new_image_1 = fields.Binary(string="Ny bild 1", attachment=False)
    new_image_2 = fields.Binary(string="Ny bild 2", attachment=False)

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
        for record in self:
            record.current_value = compute_linear_depreciation(
                purchase_price=record.price_at_purchase,
                economic_lifespan_months=record.economic_lifespan,
                installation_date=record.installation_date,
            )

    @api.depends('image_urls_json')
    def _compute_has_images(self):
        """Check if the component has any images."""
        for record in self:
            try:
                urls = json.loads(record.image_urls_json or '[]')
                record.has_images = bool(urls and len(urls) > 0)
            except (json.JSONDecodeError, TypeError):
                record.has_images = False

    def action_save_component(self):
        """Save component changes to OneCore via PUT /components/{id} and /component-installations/{id}."""
        self.ensure_one()

        # Validate required fields
        if not self.onecore_component_id:
            raise UserError("Kan inte spara: Komponenten saknar OneCore-ID.")
        if not self.model_id:
            raise UserError("Kan inte spara: Komponenten saknar modell-ID.")
        if not self.room_id:
            raise UserError("Du måste välja ett rum för komponenten.")

        # Map optional fields to payload keys
        optional_fields = {
            "serial_number": "serialNumber",
            "specifications": "specifications",
            "additional_information": "additionalInformation",
            "warranty_months": "warrantyMonths",
            "ncs_code": "ncsCode",
            "price_at_purchase": "priceAtPurchase",
            "depreciation_price_at_purchase": "depreciationPriceAtPurchase",
            "economic_lifespan": "economicLifespan",
        }

        # Build payload
        component_payload = {
            "modelId": self.model_id,
            "condition": self.condition if self.condition else "NEW",
        }

        # Add optional fields if they have values
        component_payload.update(
            {
                payload_key: getattr(self, attr_name)
                for attr_name, payload_key in optional_fields.items()
                if getattr(self, attr_name) is not None
            }
        )

        # Send payload to OneCore API
        api = core_api.CoreApi(self.env)

        try:
            # Update component fields
            api.update_component(self.onecore_component_id, component_payload)
            _logger.info(f"Successfully updated component {self.onecore_component_id}")

            # Update room/installation if installation_id exists (room_id is validated above)
            if self.installation_id:
                installation_payload = {
                    "componentId": self.onecore_component_id,
                    "spaceId": self.room_id,
                    "spaceType": PROPERTY_OBJECT_SPACE_TYPE,
                }
                api.update_component_installation(self.installation_id, installation_payload)
                _logger.info(f"Successfully updated installation {self.installation_id} to room {self.room_id}")

            # Upload any new images
            has_new_images = self._upload_new_images()

            # Reload components to refresh image URLs if new images were uploaded
            if has_new_images:
                wizard = self.wizard_id
                wizard.reload_components()
                # Return to wizard to show refreshed images
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'maintenance.component.wizard',
                    'res_id': wizard.id,
                    'view_mode': 'form',
                    'target': 'new',
                }

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

    def _upload_new_images(self):
        """Upload new images to the component instance.

        Returns:
            bool: True if images were uploaded, False otherwise
        """
        images = []
        if self.new_image_1:
            images.append((self.new_image_1, "Ny bild 1"))
        if self.new_image_2:
            images.append((self.new_image_2, "Ny bild 2"))

        if not images:
            return False

        service = ComponentOneCoreService(self.env)
        _logger.info(f"Uploading {len(images)} new image(s) to component {self.onecore_component_id}")

        result = service.upload_component_images(self.onecore_component_id, images)

        if result['success_count'] > 0:
            _logger.info(f"Successfully uploaded {result['success_count']} image(s)")
        if result['errors']:
            _logger.warning(f"Failed to upload {len(result['errors'])} image(s): {result['errors']}")

        # Clear the upload fields after successful upload
        self.write({
            'new_image_1': False,
            'new_image_2': False,
        })

        return result['success_count'] > 0

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
        uninstallation_payload = {
            "componentId": self.onecore_component_id,
            "spaceId": self.room_id,
            "spaceType": PROPERTY_OBJECT_SPACE_TYPE,
            "deinstallationDate": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        _logger.info(f"Uninstalling component {self.onecore_component_id} with payload: {uninstallation_payload}")

        try:
            api.update_component_installation(self.installation_id, uninstallation_payload)
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
