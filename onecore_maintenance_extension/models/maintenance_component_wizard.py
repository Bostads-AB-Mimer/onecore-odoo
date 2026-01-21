# -*- coding: utf-8 -*-
"""Wizard for creating and managing maintenance components."""

import json
import logging

from odoo import models, fields, api, exceptions

from .services.component_hierarchy_service import ComponentHierarchyService
from .services.component_onecore_service import ComponentOneCoreService
from .services.component_ai_analysis_service import ComponentAIAnalysisService
from .utils.depreciation import compute_linear_depreciation

_logger = logging.getLogger(__name__)


class MaintenanceComponentWizard(models.TransientModel):
    _name = "maintenance.component.wizard"
    _description = "Uppdatera/lägg till Komponent"

    # ==================== Relations ====================
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

    # ==================== Form State ====================
    form_state = fields.Selection([
        ('upload', 'Ladda upp bilder'),
        ('analyzing', 'Analyserar...'),
        ('review', 'Granska resultat'),
    ], default='upload', string="Formulärstatus")

    # ==================== Image Upload ====================
    temp_image = fields.Binary(string="Bild", attachment=False)
    temp_additional_image = fields.Binary(string="Ytterligare bild", attachment=False)
    has_image = fields.Boolean(
        string="Has Image",
        compute="_compute_has_image",
        store=False,
    )
    # Extra image fields for adding more images in review state
    form_extra_image_1 = fields.Binary(string="Extra bild 1", attachment=False)
    form_extra_image_2 = fields.Binary(string="Extra bild 2", attachment=False)

    # ==================== Component Form Fields ====================
    form_type = fields.Char(string="Typ")
    form_subtype = fields.Char(string="Undertyp")
    form_model = fields.Char(string="Modell")
    form_category = fields.Char(string="Kategori")
    form_manufacturer = fields.Char(string="Tillverkare")
    form_serial_number = fields.Char(string="Serienummer")
    form_estimated_age = fields.Char(string="Uppskattad ålder")
    form_condition = fields.Selection([
        ('NEW', 'Nyskick'),
        ('GOOD', 'Gott skick'),
        ('FAIR', 'Godtagbart skick'),
        ('POOR', 'Dåligt skick'),
        ('DAMAGED', 'Skadat'),
    ], string="Skick")
    form_specifications = fields.Text(string="Specifikationer")
    form_dimensions = fields.Char(string="Dimensioner")
    form_warranty_months = fields.Integer(string="Garanti (månader)")
    form_ncs_code = fields.Char(string="NCS-kod")
    form_coclass_code = fields.Char(string="Coclass-kod")
    form_additional_information = fields.Text(string="Ytterligare information")
    form_installation_date = fields.Date(string="Installationsdatum")

    # ==================== AI/Metadata Fields ====================
    form_confidence = fields.Float(string="AI-säkerhet", digits=(3, 2))
    form_ai_suggested = fields.Boolean(string="AI-föreslagen", default=False)
    form_model_data_loaded = fields.Boolean(
        string="Modelldata laddad",
        default=False,
        help="True if manufacturer/dimensions were loaded from an existing model"
    )

    # ==================== Price/Economic Fields ====================
    form_current_price = fields.Float(string="Inköpspris")
    form_current_install_price = fields.Float(string="Installationskostnad")
    form_economic_lifespan = fields.Integer(string="Ekonomisk livslängd (månader)")
    form_depreciation_price = fields.Float(string="Avskrivningspris")
    form_current_value = fields.Float(
        string="Nuvarande värde",
        compute="_compute_current_value",
        store=False,
    )
    form_technical_lifespan = fields.Integer(string="Teknisk livslängd (månader)")
    form_replacement_interval = fields.Integer(string="Bytesintervall (månader)")

    # ==================== Room Selection ====================
    form_room_id = fields.Char(string="Rum-ID")
    form_room_name = fields.Char(string="Rum")
    available_rooms_json = fields.Text(string="Tillgängliga rum (JSON)")

    # ==================== Category/Type/Subtype Hierarchy ====================
    form_category_id = fields.Char(string="Kategori-ID")
    form_type_id = fields.Char(string="Typ-ID")
    form_subtype_id = fields.Char(string="Undertyp-ID")
    available_categories_json = fields.Text(string="Kategorier (JSON)")
    available_types_json = fields.Text(string="Typer (JSON)")
    available_subtypes_json = fields.Text(string="Undertyper (JSON)")

    # ==================== Error Handling ====================
    error_message = fields.Text(string="Felmeddelande", readonly=True)
    api_error = fields.Boolean(string="API-fel", default=False)

    # ==================== Computed Methods ====================

    @api.depends('temp_image')
    def _compute_has_image(self):
        for record in self:
            record.has_image = bool(record.temp_image)

    @api.depends('form_current_price', 'form_economic_lifespan', 'form_installation_date')
    def _compute_current_value(self):
        """Compute current value using linear depreciation."""
        for record in self:
            record.form_current_value = compute_linear_depreciation(
                purchase_price=record.form_current_price,
                economic_lifespan_months=record.form_economic_lifespan,
                installation_date=record.form_installation_date,
            )

    # ==================== Onchange Handlers ====================

    @api.onchange('form_category_id', 'form_category')
    def _onchange_form_category_id(self):
        """Load types when category changes."""
        if not self.form_category_id:
            self.available_types_json = '[]'
            self.form_type_id = False
            self.form_type = False
            self.form_subtype_id = False
            self.form_subtype = False
            self.available_subtypes_json = '[]'
            return

        service = ComponentHierarchyService(self.env)
        types = service.load_types_for_category(self.form_category_id)
        self.available_types_json = json.dumps(types)
        self.form_type_id = False
        self.form_type = False
        self.form_subtype_id = False
        self.form_subtype = False
        self.available_subtypes_json = '[]'

    @api.onchange('form_type_id', 'form_type')
    def _onchange_form_type_id(self):
        """Load subtypes when type changes."""
        if not self.form_type_id:
            self.available_subtypes_json = '[]'
            self.form_subtype_id = False
            self.form_subtype = False
            return

        service = ComponentHierarchyService(self.env)
        subtypes = service.load_subtypes_for_type(self.form_type_id)
        self.available_subtypes_json = json.dumps(subtypes)
        self.form_subtype_id = False
        self.form_subtype = False

    @api.onchange('form_subtype_id')
    def _onchange_form_subtype_id_economics(self):
        """Load economic data from subtype."""
        service = ComponentHierarchyService(self.env)
        economic_data = service.get_economic_data_from_subtype(
            self.form_subtype_id, self.available_subtypes_json
        )
        self.form_depreciation_price = economic_data['depreciation_price']
        self.form_economic_lifespan = economic_data['economic_lifespan']
        self.form_technical_lifespan = economic_data['technical_lifespan']
        self.form_replacement_interval = economic_data['replacement_interval']

    @api.onchange('form_model')
    def _onchange_form_model(self):
        """Lookup model in OneCore when user types model name."""
        if not self.form_model:
            return

        service = ComponentHierarchyService(self.env)
        model_data = service.load_model_data(self.form_model)

        if model_data:
            if model_data.get('category_name'):
                self.form_category = model_data['category_name']
                self.form_category_id = model_data['category_id']
            if model_data.get('type_name'):
                self.form_type = model_data['type_name']
                self.form_type_id = model_data['type_id']
            if model_data.get('subtype_name'):
                self.form_subtype = model_data['subtype_name']
                self.form_subtype_id = model_data['subtype_id']

            manufacturer = model_data.get('manufacturer')
            if manufacturer and manufacturer != 'Unknown':
                self.form_manufacturer = manufacturer
            if model_data.get('warranty_months'):
                self.form_warranty_months = model_data['warranty_months']
            if model_data.get('current_price'):
                self.form_current_price = model_data['current_price']
            if model_data.get('current_install_price'):
                self.form_current_install_price = model_data['current_install_price']
            if model_data.get('dimensions'):
                self.form_dimensions = model_data['dimensions']
            if model_data.get('technical_specification'):
                self.form_specifications = model_data['technical_specification']
            if model_data.get('installation_instructions'):
                self.form_additional_information = model_data['installation_instructions']
            if model_data.get('coclass_code'):
                self.form_coclass_code = model_data['coclass_code']

            self.form_model_data_loaded = True
            _logger.info(f"Auto-filled form from OneCore model: {self.form_model}")
        else:
            self.form_model_data_loaded = False

    # ==================== Action Methods ====================

    def action_analyze_images(self):
        """Upload images to AI service and analyze."""
        self.ensure_one()

        if not self.temp_image:
            raise exceptions.UserError("Du måste ladda upp minst en bild")

        # Store images before write operations (they need to be preserved)
        temp_image = self.temp_image
        temp_additional_image = self.temp_additional_image

        self.write({'form_state': 'analyzing', 'api_error': False, 'error_message': ''})

        service = ComponentAIAnalysisService(self.env)
        result = service.analyze_images(temp_image, temp_additional_image)

        if result.get('error'):
            self.write({
                'form_state': 'review',
                'api_error': True,
                'error_message': result['error_message'],
                'temp_image': temp_image,
                'temp_additional_image': temp_additional_image,
            })
        else:
            # Preserve images in the result before writing
            result['temp_image'] = temp_image
            result['temp_additional_image'] = temp_additional_image
            self.write(result)

        return self._return_wizard_action()

    def action_manual_entry(self):
        """Skip AI and go directly to manual form entry."""
        self.ensure_one()
        self.write({
            'form_state': 'review',
            'form_ai_suggested': False,
            'api_error': False,
            'form_type': False,
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
        return self._return_wizard_action()

    def action_add_to_list(self):
        """Create component in OneCore and add to list."""
        self.ensure_one()

        if not self.form_room_id:
            raise exceptions.UserError("Du måste välja ett rum för komponenten.")

        if not self.form_subtype_id:
            raise exceptions.UserError(
                "Undertyp saknas. Undertypen behöver skapas upp i ONEcore."
            )

        if not self.form_serial_number:
            raise exceptions.UserError("Serienummer saknas.")

        form_data = self._get_form_data()
        service = ComponentOneCoreService(self.env)

        try:
            result = service.create_component(form_data, self.form_room_id)

            _logger.info(
                f"Successfully created component in OneCore: "
                f"{self.form_model or self.form_type}"
            )

            # Upload images to the created component instance
            component_instance_id = self._extract_component_instance_id(result)
            if component_instance_id:
                self._upload_images_to_component(service, component_instance_id)

            # Reload all components from OneCore to get correct installation_id
            self.reload_components()

            # Reset the form for next entry
            self._reset_form_fields()

            return self._return_wizard_action()

        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_msg = e.response.text
                except Exception:
                    pass
            _logger.error(f"Failed to create component in OneCore: {error_msg}")

            # Check if error is related to missing/invalid subtype
            if 'componentSubtypeId' in error_msg:
                raise exceptions.UserError(
                    "Undertyp saknas. Undertypen behöver skapas upp i ONEcore."
                )

            raise exceptions.UserError(
                "Kunde inte skapa komponenten. "
                "Försök igen eller kontakta support om problemet kvarstår."
            )

    def _extract_component_instance_id(self, result):
        """Extract the component instance ID from the create_component result.

        Args:
            result: Response from create_component API call

        Returns:
            str: The component instance ID, or None if not found
        """
        if not result:
            return None

        # Try common response structures
        # The API might return the component directly or wrapped in 'content'
        component_data = result.get('content', result)

        # Try to get the component ID
        component_id = component_data.get('id')
        if component_id:
            return component_id

        # If it's a nested structure, try to find the component
        if isinstance(component_data, dict):
            for key in ['component', 'componentInstance', 'data']:
                if key in component_data and isinstance(component_data[key], dict):
                    component_id = component_data[key].get('id')
                    if component_id:
                        return component_id

        _logger.warning(f"Could not extract component instance ID from result: {result}")
        return None

    def _upload_images_to_component(self, service, component_instance_id):
        """Upload all captured images to a component instance.

        Args:
            service: ComponentOneCoreService instance
            component_instance_id: The component instance ID to attach images to
        """
        # Collect all images with their captions
        images = []

        if self.temp_image:
            images.append((self.temp_image, "Huvudbild"))
        if self.temp_additional_image:
            images.append((self.temp_additional_image, "Ytterligare bild"))
        if self.form_extra_image_1:
            images.append((self.form_extra_image_1, "Extra bild 1"))
        if self.form_extra_image_2:
            images.append((self.form_extra_image_2, "Extra bild 2"))

        if not images:
            _logger.info("No images to upload for component")
            return

        _logger.info(f"Uploading {len(images)} image(s) to component {component_instance_id}")
        result = service.upload_component_images(component_instance_id, images)

        if result['success_count'] > 0:
            _logger.info(f"Successfully uploaded {result['success_count']} image(s)")
        if result['errors']:
            _logger.warning(f"Failed to upload {len(result['errors'])} image(s): {result['errors']}")

    def action_reset_form(self):
        """Clear form and return to upload state."""
        self.ensure_one()
        self._reset_form_fields()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.component.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context),
        }

    def action_retry_upload(self):
        """Return to upload state after error."""
        self.ensure_one()
        self.write({
            'form_state': 'upload',
            'api_error': False,
            'error_message': '',
        })
        return self._return_wizard_action()

    def action_save_all(self):
        """Close the wizard. Components are saved immediately on creation."""
        return {'type': 'ir.actions.act_window_close'}

    # ==================== CRUD Methods ====================

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to load OneCore components after wizard has a database ID."""
        wizards = super().create(vals_list)
        for wizard in wizards:
            wizard._load_onecore_components()
        return wizards

    def reload_components(self):
        """Clear and reload components from OneCore API."""
        self.ensure_one()
        self.component_ids.unlink()
        self._load_onecore_components()

    def _load_onecore_components(self):
        """Load components from OneCore API for this wizard."""
        self.ensure_one()

        if not self.maintenance_request_id:
            return

        request = self.maintenance_request_id
        rental_property = request.rental_property_id

        if not rental_property or not rental_property.rental_property_id:
            return

        service = ComponentOneCoreService(self.env)
        rooms_json, categories_json, component_data_list = service.load_components_for_residence(
            rental_property.rental_property_id, request.space_caption
        )

        self.available_rooms_json = rooms_json
        self.available_categories_json = categories_json

        ComponentLine = self.env['maintenance.component.line']
        for comp_data in component_data_list:
            comp_data['wizard_id'] = self.id
            ComponentLine.create(comp_data)

    @api.model
    def search_component_models(self, search_text, type_id=None, subtype_id=None):
        """Search component models for autocomplete dropdown."""
        service = ComponentOneCoreService(self.env)
        return service.search_models(search_text, type_id, subtype_id)

    # ==================== Helper Methods ====================

    def _return_wizard_action(self):
        """Return action to reload the wizard form."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.component.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _reset_form_fields(self):
        """Reset form fields to initial state without returning an action."""
        self.write({
            'form_state': 'upload',
            'temp_image': False,
            'temp_additional_image': False,
            'form_extra_image_1': False,
            'form_extra_image_2': False,
            'form_type': False,
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
            'form_coclass_code': False,
            'form_additional_information': False,
            'form_installation_date': False,
            'form_confidence': 0.0,
            'form_ai_suggested': False,
            'form_model_data_loaded': False,
            'api_error': False,
            'error_message': '',
            'form_room_id': False,
            'form_room_name': False,
            'form_category_id': False,
            'form_type_id': False,
            'form_subtype_id': False,
            'form_current_price': 0,
            'form_current_install_price': 0,
            'form_economic_lifespan': 0,
            'form_depreciation_price': 0,
            'form_technical_lifespan': 0,
            'form_replacement_interval': 0,
        })

    def _get_form_data(self):
        """Extract form data as a dict for service calls."""
        return {
            'model': self.form_model,
            'subtype_id': self.form_subtype_id,
            'serial_number': self.form_serial_number,
            'warranty_months': self.form_warranty_months,
            'current_price': self.form_current_price,
            'current_install_price': self.form_current_install_price,
            'depreciation_price': self.form_depreciation_price,
            'economic_lifespan': self.form_economic_lifespan,
            'manufacturer': self.form_manufacturer,
            'condition': self.form_condition,
            'specifications': self.form_specifications,
            'dimensions': self.form_dimensions,
            'additional_information': self.form_additional_information,
            'ncs_code': self.form_ncs_code,
            'installation_date': self.form_installation_date,
        }
