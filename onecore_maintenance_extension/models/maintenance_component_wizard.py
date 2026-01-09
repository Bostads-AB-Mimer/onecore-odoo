# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions
from ...onecore_api import core_api
import base64
import logging
import io
import json
from datetime import datetime

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

_logger = logging.getLogger(__name__)

# Max image dimension (width or height) for AI analysis
MAX_IMAGE_DIMENSION = 1920
# JPEG quality for compressed images
JPEG_QUALITY = 85


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

    # Computed field for button visibility
    has_image = fields.Boolean(
        string="Has Image",
        compute="_compute_has_image",
        store=False,
    )

    @api.depends('temp_image')
    def _compute_has_image(self):
        for record in self:
            record.has_image = bool(record.temp_image)

    # Fields for the form being filled (before adding to list)
    form_type = fields.Char(string="Typ")
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

    # Price and economic fields
    form_price_at_purchase = fields.Float(string="Inköpspris")
    form_current_price = fields.Float(string="Nuvarande pris")
    form_current_install_price = fields.Float(string="Installationspris")
    form_installation_cost = fields.Float(string="Installationskostnad")
    form_economic_lifespan = fields.Integer(string="Ekonomisk livslängd (år)")

    # Room selection
    form_room_id = fields.Char(string="Rum-ID")
    form_room_name = fields.Char(string="Rum")
    available_rooms_json = fields.Text(string="Tillgängliga rum (JSON)")

    # Category/Type/Subtype selection with IDs
    form_category_id = fields.Char(string="Kategori-ID")
    form_type_id = fields.Char(string="Typ-ID")
    form_subtype_id = fields.Char(string="Undertyp-ID")

    # Available options (JSON for frontend)
    available_categories_json = fields.Text(string="Kategorier (JSON)")
    available_types_json = fields.Text(string="Typer (JSON)")
    available_subtypes_json = fields.Text(string="Undertyper (JSON)")

    # Error handling
    error_message = fields.Text(string="Felmeddelande", readonly=True)
    api_error = fields.Boolean(string="API-fel", default=False)

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

        try:
            api = core_api.CoreApi(self.env)
            types = api.fetch_component_types(self.form_category_id)
            self.available_types_json = json.dumps(types or [])
            # Clear dependent fields
            self.form_type_id = False
            self.form_type = False
            self.form_subtype_id = False
            self.form_subtype = False
            self.available_subtypes_json = '[]'
        except Exception as e:
            _logger.warning(f"Failed to fetch component types: {e}")

    @api.onchange('form_type_id', 'form_type')
    def _onchange_form_type_id(self):
        """Load subtypes when type changes."""
        if not self.form_type_id:
            self.available_subtypes_json = '[]'
            self.form_subtype_id = False
            self.form_subtype = False
            return

        try:
            api = core_api.CoreApi(self.env)
            subtypes = api.fetch_component_subtypes(self.form_type_id)
            self.available_subtypes_json = json.dumps(subtypes or [])
            # Clear dependent field
            self.form_subtype_id = False
            self.form_subtype = False
        except Exception as e:
            _logger.warning(f"Failed to fetch component subtypes: {e}")

    @api.onchange('form_model')
    def _onchange_form_model(self):
        """Lookup model in OneCore when user types model name."""
        if not self.form_model:
            return

        try:
            api = core_api.CoreApi(self.env)
            models = api.fetch_component_models(self.form_model, page=1, limit=1)

            if models and len(models) > 0:
                onecore_model = models[0]
                subtype_data = onecore_model.get('subtype', {}) or {}
                component_type_data = subtype_data.get('componentType', {}) or {}
                category_data = component_type_data.get('category', {}) or {}

                # Update names and IDs
                if category_data.get('categoryName'):
                    self.form_category = category_data.get('categoryName')
                    self.form_category_id = category_data.get('id')
                if component_type_data.get('typeName'):
                    self.form_type = component_type_data.get('typeName')
                    self.form_type_id = component_type_data.get('id')
                if subtype_data.get('subTypeName'):
                    self.form_subtype = subtype_data.get('subTypeName')
                    self.form_subtype_id = subtype_data.get('id')
                manufacturer = onecore_model.get('manufacturer')
                if manufacturer and manufacturer != 'Unknown':
                    self.form_manufacturer = manufacturer

                # Populate warranty months from model if available
                warranty_months = onecore_model.get('warrantyMonths')
                if warranty_months:
                    self.form_warranty_months = warranty_months

                # Populate price and economic fields from model if available
                current_price = onecore_model.get('currentPrice')
                if current_price:
                    self.form_current_price = current_price

                current_install_price = onecore_model.get('currentInstallPrice')
                if current_install_price:
                    self.form_current_install_price = current_install_price

                economic_lifespan = onecore_model.get('economicLifespan')
                if economic_lifespan:
                    self.form_economic_lifespan = economic_lifespan

                _logger.info(f"Auto-filled form from OneCore model: {self.form_model}")
        except Exception as e:
            _logger.warning(f"Failed to fetch component model from OneCore: {e}")

    def _compress_image(self, image_base64):
        """Compress and resize image if too large.

        Resizes images to max MAX_IMAGE_DIMENSION pixels on longest side
        and compresses as JPEG with JPEG_QUALITY quality.

        Args:
            image_base64: Base64-encoded image string

        Returns:
            tuple: (compressed_base64_string, mime_type)
        """
        if not HAS_PIL:
            _logger.warning("PIL not available, skipping image compression")
            return image_base64, self._detect_image_mime_type(image_base64)

        try:
            # Decode base64 to bytes
            image_bytes = base64.b64decode(image_base64)

            # Open image with PIL
            img = Image.open(io.BytesIO(image_bytes))

            # Get original dimensions
            original_width, original_height = img.size
            _logger.info(f"Original image size: {original_width}x{original_height}")

            # Check if resizing is needed
            if original_width <= MAX_IMAGE_DIMENSION and original_height <= MAX_IMAGE_DIMENSION:
                # Image is small enough, check if it's already JPEG
                if img.format == 'JPEG':
                    _logger.info("Image already small enough and JPEG, no compression needed")
                    return image_base64, 'image/jpeg'

            # Calculate new dimensions maintaining aspect ratio
            if original_width > original_height:
                if original_width > MAX_IMAGE_DIMENSION:
                    new_width = MAX_IMAGE_DIMENSION
                    new_height = int(original_height * (MAX_IMAGE_DIMENSION / original_width))
                else:
                    new_width, new_height = original_width, original_height
            else:
                if original_height > MAX_IMAGE_DIMENSION:
                    new_height = MAX_IMAGE_DIMENSION
                    new_width = int(original_width * (MAX_IMAGE_DIMENSION / original_height))
                else:
                    new_width, new_height = original_width, original_height

            # Resize if dimensions changed
            if (new_width, new_height) != (original_width, original_height):
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                _logger.info(f"Resized image to: {new_width}x{new_height}")

            # Convert to RGB if necessary (for JPEG compatibility)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            # Save as JPEG to buffer
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
            compressed_bytes = buffer.getvalue()

            # Encode back to base64
            compressed_base64 = base64.b64encode(compressed_bytes).decode('utf-8')

            original_size = len(image_base64)
            compressed_size = len(compressed_base64)
            _logger.info(f"Image compressed: {original_size} -> {compressed_size} bytes ({100 * compressed_size / original_size:.1f}%)")

            return compressed_base64, 'image/jpeg'

        except Exception as e:
            _logger.warning(f"Image compression failed, using original: {e}")
            return image_base64, self._detect_image_mime_type(image_base64)

    def _detect_image_mime_type(self, image_data):
        """Detect MIME type from image magic bytes.

        Args:
            image_data: Either base64 string or raw bytes

        Returns:
            str: MIME type string (e.g., 'image/jpeg', 'image/png')
        """
        # If it's a base64 string, decode first few bytes for detection
        if isinstance(image_data, str):
            try:
                header_bytes = base64.b64decode(image_data[:32])
            except Exception:
                return 'image/jpeg'
        else:
            header_bytes = image_data[:16] if len(image_data) >= 16 else image_data

        # Check magic bytes for common image formats
        if header_bytes[:3] == b'\xff\xd8\xff':
            return 'image/jpeg'
        elif header_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        elif header_bytes[:6] in (b'GIF87a', b'GIF89a'):
            return 'image/gif'
        elif header_bytes[:4] == b'RIFF' and len(header_bytes) >= 12 and header_bytes[8:12] == b'WEBP':
            return 'image/webp'
        return 'image/jpeg'  # fallback

    def _image_to_data_url(self, image_binary, mime_type=None, compress=True):
        """Convert image to data URL format.

        Handles both:
        - Already base64-encoded strings (from Odoo Binary fields)
        - Raw binary data

        Args:
            image_binary: Image data (base64 string or bytes)
            mime_type: Optional MIME type override. If None, auto-detected.
            compress: If True, compress large images before creating data URL.

        Returns:
            str: Data URL in format "data:<mime_type>;base64,<data>"
        """
        if not image_binary:
            return None

        # Odoo Binary fields return base64 as string or bytes
        if isinstance(image_binary, str):
            base64_string = image_binary
        elif isinstance(image_binary, bytes):
            try:
                # Check if already base64 (ASCII-decodable)
                decoded_str = image_binary.decode('ascii')
                base64.b64decode(decoded_str)  # Validate it's valid base64
                base64_string = decoded_str
            except (UnicodeDecodeError, ValueError):
                # It's raw binary data, encode it
                base64_string = base64.b64encode(image_binary).decode('utf-8')
        else:
            _logger.warning(f"Unexpected image_binary type: {type(image_binary)}")
            return None

        # Compress image if requested (for API calls)
        if compress:
            base64_string, mime_type = self._compress_image(base64_string)
        elif mime_type is None:
            # Auto-detect MIME type if not provided and not compressing
            mime_type = self._detect_image_mime_type(base64_string)

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

            # Try to find existing model in OneCore
            model_name = content.get('model')
            onecore_model = None
            if model_name:
                try:
                    models = api.fetch_component_models(model_name, page=1, limit=1)
                    if models and len(models) > 0:
                        onecore_model = models[0]
                        _logger.info(f"Found existing model in OneCore: {model_name}")
                except Exception as e:
                    _logger.warning(f"Failed to fetch component model from OneCore: {e}")

            # Initialize IDs
            form_category_id = None
            form_type_id = None
            form_subtype_id = None

            # Initialize price/economic fields
            form_current_price = 0
            form_current_install_price = 0
            form_economic_lifespan = 0

            # Extract OneCore data if model found, otherwise use AI values
            if onecore_model:
                subtype_data = onecore_model.get('subtype', {}) or {}
                component_type_data = subtype_data.get('componentType', {}) or {}
                category_data = component_type_data.get('category', {}) or {}

                form_category = category_data.get('categoryName') or content.get('componentCategory')
                form_category_id = category_data.get('id')
                form_type = component_type_data.get('typeName') or content.get('componentType')
                form_type_id = component_type_data.get('id')
                form_subtype = subtype_data.get('subTypeName') or content.get('componentSubtype')
                form_subtype_id = subtype_data.get('id')
                form_manufacturer = onecore_model.get('manufacturer')
                # Use AI manufacturer if OneCore has "Unknown"
                if not form_manufacturer or form_manufacturer == 'Unknown':
                    form_manufacturer = content.get('manufacturer')

                # Extract price/economic fields from OneCore model
                form_current_price = onecore_model.get('currentPrice', 0)
                form_current_install_price = onecore_model.get('currentInstallPrice', 0)
                form_economic_lifespan = onecore_model.get('economicLifespan', 0)
            else:
                form_category = content.get('componentCategory')
                form_type = content.get('componentType')
                form_subtype = content.get('componentSubtype')
                form_manufacturer = content.get('manufacturer')

                # Try to match AI values to OneCore categories/types/subtypes
                if form_category:
                    try:
                        categories = api.fetch_component_categories()
                        if categories:
                            matched_cat = next((c for c in categories if c.get('categoryName') == form_category), None)
                            if matched_cat:
                                form_category_id = matched_cat.get('id')
                                # Load types for this category
                                types = api.fetch_component_types(form_category_id)
                                if types and form_type:
                                    matched_type = next((t for t in types if t.get('typeName') == form_type), None)
                                    if matched_type:
                                        form_type_id = matched_type.get('id')
                                        # Load subtypes for this type
                                        subtypes = api.fetch_component_subtypes(form_type_id)
                                        if subtypes and form_subtype:
                                            matched_subtype = next((s for s in subtypes if s.get('subTypeName') == form_subtype), None)
                                            if matched_subtype:
                                                form_subtype_id = matched_subtype.get('id')
                    except Exception as e:
                        _logger.warning(f"Failed to match AI values to OneCore: {e}")

            # Map AI response to form fields
            self.write({
                'form_type': form_type,
                'form_type_id': form_type_id,
                'form_subtype': form_subtype,
                'form_subtype_id': form_subtype_id,
                'form_category': form_category,
                'form_category_id': form_category_id,
                'form_model': content.get('model'),
                'form_manufacturer': form_manufacturer,
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
                # Price/economic fields from OneCore model
                'form_current_price': form_current_price,
                'form_current_install_price': form_current_install_price,
                'form_economic_lifespan': form_economic_lifespan,
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

        # Return action to reload the form with updated values
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.component.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_add_to_list(self):
        """Create component in OneCore and add to list."""
        self.ensure_one()

        # Validate required fields
        if not self.form_room_id:
            raise exceptions.UserError("Du måste välja ett rum för komponenten.")

        api = core_api.CoreApi(self.env)

        # Build payload for OneCore API
        # Use today's date if no installation date provided (required field)
        # Convert to full ISO 8601 datetime format (YYYY-MM-DDTHH:MM:SSZ)
        if self.form_installation_date:
            installation_date = datetime.combine(self.form_installation_date, datetime.min.time()).isoformat() + "Z"
        else:
            installation_date = datetime.combine(fields.Date.today(), datetime.min.time()).isoformat() + "Z"

        payload = {
            # Required fields (always)
            "modelName": self.form_model or "Unknown",
            "componentSubtypeId": self.form_subtype_id,
            "serialNumber": self.form_serial_number or "",
            "componentWarrantyMonths": self.form_warranty_months or 0,
            "priceAtPurchase": self.form_price_at_purchase or 0,
            "depreciationPriceAtPurchase": self.form_price_at_purchase or 0,
            "economicLifespan": self.form_economic_lifespan or 0,
            "spaceId": self.form_room_id,
            "spaceType": "PropertyObject",
            "installationDate": installation_date,
            "installationCost": self.form_installation_cost or 0,
            # Conditionally required (for new models) - always include
            "manufacturer": self.form_manufacturer or "Unknown",
            "currentPrice": self.form_current_price or 0,
            "currentInstallPrice": self.form_current_install_price or 0,
            "modelWarrantyMonths": self.form_warranty_months or 0,
            # Always included optional fields
            "warrantyStartDate": installation_date,
            "quantity": 1,
            "status": "ACTIVE",
        }

        # Only include optional string fields if they have values (API validates format)
        if self.form_specifications:
            payload["technicalSpecification"] = self.form_specifications
            payload["specifications"] = self.form_specifications
        if self.form_dimensions:
            payload["dimensions"] = self.form_dimensions
        if self.form_additional_information:
            payload["additionalInformation"] = self.form_additional_information
        if self.form_ncs_code:
            payload["ncsCode"] = self.form_ncs_code

        try:
            result = api.create_component(payload)
            # Extract component ID from response
            onecore_id = None
            if isinstance(result, dict):
                onecore_id = result.get('content', {}).get('id') or result.get('id')

            _logger.info(f"Successfully created component in OneCore: {self.form_model or self.form_type}")

            # Add to local list as already saved to OneCore
            self.env['maintenance.component.line'].create({
                'wizard_id': self.id,
                'image': self.temp_image,
                'additional_image': self.temp_additional_image,
                'typ': self.form_type,
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
                'room_id': self.form_room_id,
                'room_name': self.form_room_name,
                'category_id': self.form_category_id,
                'type_id': self.form_type_id,
                'subtype_id': self.form_subtype_id,
                'is_from_onecore': True,
                'onecore_component_id': onecore_id,
            })

            # Reset form for next entry
            return self.action_reset_form()

        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_msg = e.response.text
                except:
                    pass
            _logger.error(f"Failed to create component in OneCore: {error_msg}")
            raise exceptions.UserError(f"Kunde inte skapa komponenten: {error_msg}")

    def action_reset_form(self):
        """Clear form and return to upload state."""
        self.ensure_one()

        self.write({
            'form_state': 'upload',
            'temp_image': False,
            'temp_additional_image': False,
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
            'form_ai_suggested': False,
            'api_error': False,
            'error_message': '',
            # Clear ID fields
            'form_room_id': False,
            'form_room_name': False,
            'form_category_id': False,
            'form_type_id': False,
            'form_subtype_id': False,
            # Clear price/economic fields
            'form_price_at_purchase': 0,
            'form_current_price': 0,
            'form_current_install_price': 0,
            'form_installation_cost': 0,
            'form_economic_lifespan': 0,
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
        """Close the wizard. Components are saved immediately on creation."""
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        # Get maintenance request from context
        request_id = self.env.context.get('default_maintenance_request_id')
        if not request_id:
            return res

        request = self.env['maintenance.request'].browse(request_id)

        # Only fetch from OneCore for apartment errands
        if request.space_caption != 'Lägenhet':
            return res

        # Get rental property ID
        rental_property = request.rental_property_id
        if not rental_property or not rental_property.rental_property_id:
            return res

        try:
            api = core_api.CoreApi(self.env)

            # Fetch residence to get residenceId
            residence = api.fetch_residence(rental_property.rental_property_id)
            if not residence or not residence.get('id'):
                return res

            residence_id = residence['id']

            # Fetch rooms
            rooms = api.fetch_rooms(residence_id)
            if not rooms:
                return res

            # Store available rooms for dropdown (use propertyObjectId for component creation)
            res['available_rooms_json'] = json.dumps([
                {'id': r.get('propertyObjectId'), 'name': r.get('name', 'Okänt rum')}
                for r in rooms
            ])

            # Fetch and store component categories
            try:
                categories = api.fetch_component_categories()
                if categories:
                    res['available_categories_json'] = json.dumps(categories)
            except Exception as e:
                _logger.warning(f"Failed to fetch component categories: {e}")

            components = []
            for room in rooms:
                room_id = room.get('propertyObjectId')
                room_name = room.get('name', 'Okänt rum')

                room_components = api.fetch_components_by_room(room_id)
                if room_components:
                    for comp in room_components:
                        # Extract nested data from API response structure
                        model_data = comp.get('model', {}) or {}
                        subtype_data = model_data.get('subtype', {}) or {}
                        component_type_data = subtype_data.get('componentType', {}) or {}
                        category_data = component_type_data.get('category', {}) or {}

                        # Get installation date from componentInstallations array
                        installations = comp.get('componentInstallations', [])
                        install_date = None
                        if installations:
                            install_date_str = installations[0].get('installationDate')
                            if install_date_str:
                                install_date = install_date_str[:10]  # Extract YYYY-MM-DD

                        components.append((0, 0, {
                            'typ': component_type_data.get('typeName'),
                            'subtype': subtype_data.get('subTypeName'),
                            'category': category_data.get('categoryName'),
                            'model': model_data.get('modelName'),
                            'manufacturer': model_data.get('manufacturer'),
                            'serial_number': comp.get('serialNumber'),
                            'warranty_months': comp.get('warrantyMonths'),
                            'specifications': comp.get('specifications'),
                            'ncs_code': comp.get('ncsCode'),
                            'additional_information': comp.get('additionalInformation'),
                            'installation_date': install_date,
                            'room_name': room_name,
                            'is_from_onecore': True,
                            'onecore_component_id': comp.get('id'),
                        }))

            res['component_ids'] = components
        except Exception as e:
            _logger.warning(f"Failed to fetch components from OneCore: {e}")

        return res

    @api.model
    def search_component_models(self, search_text, type_id=None, subtype_id=None):
        """Search component models for autocomplete dropdown.

        Args:
            search_text: Model name to search for (minimum 2 characters)
            type_id: Optional component type ID to filter by
            subtype_id: Optional component subtype ID to filter by

        Returns:
            list: List of model dicts with modelName, manufacturer, and label for dropdown
        """
        if not search_text or len(search_text) < 2:
            return []

        try:
            api = core_api.CoreApi(self.env)
            models = api.fetch_component_models(
                search_text,
                page=1,
                limit=5,
                type_id=type_id,
                subtype_id=subtype_id
            )
            # Return simplified results for dropdown
            return [
                {
                    'modelName': m.get('modelName'),
                    'manufacturer': m.get('manufacturer'),
                    'label': f"{m.get('modelName')} ({m.get('manufacturer', 'Okänd')})"
                }
                for m in (models or [])
            ]
        except Exception as e:
            _logger.warning(f"Failed to search component models: {e}")
            return []
