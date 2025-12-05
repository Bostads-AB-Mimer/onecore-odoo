# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions
from ...onecore_api import core_api
import base64
import logging

_logger = logging.getLogger(__name__)


class MaintenanceComponentWizard(models.TransientModel):
    _name = "maintenance.component.wizard"
    _description = "Uppdatera/lägg till Komponent"

    maintenance_request_id = fields.Many2one(
        "maintenance.request",
        string="Underhållsärende",
        required=False,
        readonly=False,
    )
    component_ids = fields.One2many(
        "maintenance.component.line",
        "wizard_id",
        string="Komponenter",
    )

    # Form state (upload → analyzing → review)
    form_state = fields.Selection([
        ('upload', 'Ladda upp bilder'),
        ('analyzing', 'Analyserar...'),
        ('review', 'Granska resultat'),
    ], default='upload', string="Formulärstatus")

    # Temporary image storage for upload
    temp_image = fields.Binary(string="Bild", attachment=False)
    temp_additional_image = fields.Binary(string="Ytterligare bild", attachment=False)

    # Fields for the form being filled (before adding to list)
    form_component = fields.Char(string="Komponent")
    form_subtype = fields.Char(string="Undertyp")
    form_model = fields.Char(string="Modell")
    form_category = fields.Char(string="Kategori")
    form_manufacturer = fields.Char(string="Tillverkare")
    form_serial_number = fields.Char(string="Serienummer")
    form_estimated_age = fields.Char(string="Uppskattad ålder")
    form_condition = fields.Char(string="Skick")
    form_specifications = fields.Text(string="Specifikationer")
    form_dimensions = fields.Char(string="Dimensioner")
    form_warranty_months = fields.Integer(string="Garanti (månader)")
    form_ncs_code = fields.Char(string="NCS-kod")
    form_additional_information = fields.Text(string="Ytterligare information")
    form_installation_date = fields.Date(string="Installationsdatum")
    form_confidence = fields.Float(string="AI-säkerhet", digits=(3, 2))
    form_ai_suggested = fields.Boolean(string="AI-föreslagen", default=False)

    # Error handling
    error_message = fields.Text(string="Felmeddelande", readonly=True)
    api_error = fields.Boolean(string="API-fel", default=False)

    def _derive_category(self, component_type):
        """Map component type to category."""
        return component_type or ''

    def _image_to_data_url(self, image_binary, mime_type='image/jpeg'):
        """Convert binary image to data URL format."""
        if not image_binary:
            return None
        base64_string = base64.b64encode(image_binary).decode('utf-8')
        return f"data:{mime_type};base64,{base64_string}"

    def action_analyze_images(self):
        """Upload images to AI service and analyze."""
        self.ensure_one()

        if not self.temp_image:
            raise exceptions.UserError("Du måste ladda upp minst en bild")

        # Change to analyzing state
        self.write({'form_state': 'analyzing', 'api_error': False, 'error_message': ''})

        try:
            api = core_api.CoreApi(self.env)

            # Prepare payload with data URL format
            payload = {"image": self._image_to_data_url(self.temp_image)}
            if self.temp_additional_image:
                payload["additionalImage"] = self._image_to_data_url(self.temp_additional_image)

            # Log the first 100 chars of the payload for debugging
            _logger.info(f"Sending payload with image data URL prefix: {payload['image'][:100] if payload.get('image') else 'None'}")

            # Call analyze endpoint
            response = api.request("POST", "/components/analyze-image", json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()

            # Extract from response
            content = result.get('content', {})

            # Map AI response to form fields
            self.write({
                'form_component': content.get('componentType'),
                'form_subtype': content.get('componentSubtype'),
                'form_category': self._derive_category(content.get('componentType')),
                'form_model': content.get('model'),
                'form_manufacturer': content.get('manufacturer'),
                'form_serial_number': content.get('serialNumber'),
                'form_estimated_age': content.get('estimatedAge'),
                'form_condition': content.get('condition'),
                'form_specifications': content.get('specifications'),
                'form_dimensions': content.get('dimensions'),
                'form_warranty_months': content.get('warrantyMonths'),
                'form_ncs_code': content.get('ncsCode'),
                'form_additional_information': content.get('additionalInformation'),
                'form_confidence': content.get('confidence', 0.0),
                'form_ai_suggested': True,
                'form_state': 'review',
            })

            # Return action to reload the form with updated values
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'maintenance.component.wizard',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }

        except Exception as e:
            _logger.error(f"AI analysis failed: {str(e)}", exc_info=True)

            # Try to get more details from the response if it's an HTTP error
            error_detail = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = f"{str(e)}\n\nAPI Response: {e.response.text}"
                    _logger.error(f"API Response body: {e.response.text}")
                except:
                    pass

            self.write({
                'form_state': 'review',
                'api_error': True,
                'error_message': f"Kunde inte analysera bilderna: {error_detail}\n\nKontrollera att bilderna är tydliga och försök igen."
            })
            # Return action to reload the form with error message
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'maintenance.component.wizard',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }

    def action_manual_entry(self):
        """Skip AI and go directly to manual form entry."""
        self.ensure_one()

        # Clear all form fields and set manual mode
        self.write({
            'form_state': 'review',
            'form_ai_suggested': False,
            'api_error': False,
            'form_component': False,
            'form_subtype': False,
            'form_model': False,
            'form_category': False,
            'form_manufacturer': False,
            'form_serial_number': False,
            'form_estimated_age': False,
            'form_condition': False,
            'form_specifications': False,
            'form_dimensions': False,
            'form_warranty_months': False,
            'form_ncs_code': False,
            'form_additional_information': False,
            'form_installation_date': False,
            'form_confidence': 0.0,
        })

        # Return action to reload the form with updated values
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.component.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_add_to_list(self):
        """Add component from form to the list."""
        self.ensure_one()

        # Create new component line from form fields
        self.env['maintenance.component.line'].create({
            'wizard_id': self.id,
            'image': self.temp_image,
            'additional_image': self.temp_additional_image,
            'component': self.form_component,
            'subtype': self.form_subtype,
            'model': self.form_model,
            'category': self.form_category,
            'manufacturer': self.form_manufacturer,
            'serial_number': self.form_serial_number,
            'estimated_age': self.form_estimated_age,
            'condition': self.form_condition,
            'specifications': self.form_specifications,
            'dimensions': self.form_dimensions,
            'warranty_months': self.form_warranty_months,
            'ncs_code': self.form_ncs_code,
            'additional_information': self.form_additional_information,
            'installation_date': self.form_installation_date,
            'confidence': self.form_confidence,
            'ai_suggested': self.form_ai_suggested,
            'manually_reviewed': True,
        })

        # Reset form for next entry
        return self.action_reset_form()

    def action_reset_form(self):
        """Clear form and return to upload state."""
        self.ensure_one()

        self.write({
            'form_state': 'upload',
            'temp_image': False,
            'temp_additional_image': False,
            'form_component': False,
            'form_subtype': False,
            'form_model': False,
            'form_category': False,
            'form_manufacturer': False,
            'form_serial_number': False,
            'form_estimated_age': False,
            'form_condition': False,
            'form_specifications': False,
            'form_dimensions': False,
            'form_warranty_months': False,
            'form_ncs_code': False,
            'form_additional_information': False,
            'form_installation_date': False,
            'form_confidence': 0.0,
            'form_ai_suggested': False,
            'api_error': False,
            'error_message': '',
        })

        # Return action to reload the form with cleared fields
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.component.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_retry_upload(self):
        """Return to upload state after error."""
        self.ensure_one()

        self.write({
            'form_state': 'upload',
            'api_error': False,
            'error_message': '',
        })

        # Return action to reload the form in upload state
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.component.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_save_all(self):
        """
        Save components to backend (stub for now).
        Future: POST to /components endpoint
        """
        self.ensure_one()

        # TODO: Implement POST to /components endpoint
        # For now, just close the wizard
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Add dummy data for demonstration
        res["component_ids"] = [
            (0, 0, {
                "component": "Kylskåp",
                "installation_date": "2020-01-15",
            }),
            (0, 0, {
                "component": "Spis",
                "installation_date": "2019-05-20",
            }),
            (0, 0, {
                "component": "Diskmaskin",
                "installation_date": "2021-03-10",
            }),
        ]
        return res
