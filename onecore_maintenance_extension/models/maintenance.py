import urllib.parse
import base64
import uuid
import requests
import logging

from odoo import api, fields, models, _

from ...onecore_api import core_api
from .handlers import HandlerFactory, BaseMaintenanceHandler
from .utils import validators
from .services import (
    FieldChangeTracker,
    RecordManagementService,
    FormFieldService,
    ExternalContractorService,
    MaintenanceStageManager,
)
from .constants import (
    SORTED_SPACES,
    SEARCH_TYPES,
    PRIORITY_OPTIONS,
    CREATION_ORIGINS,
    FORM_STATES,
)
from .mixins import (
    SearchFieldsMixin,
    PropertyFieldsMixin,
    BuildingFieldsMixin,
    StaircaseFieldsMixin,
    RentalPropertyFieldsMixin,
    MaintenanceUnitFieldsMixin,
    TenantFieldsMixin,
    LeaseFieldsMixin,
    ParkingSpaceFieldsMixin,
    FacilityFieldsMixin,
)

_logger = logging.getLogger(__name__)


class OneCoreMaintenanceRequest(
    SearchFieldsMixin,
    PropertyFieldsMixin,
    BuildingFieldsMixin,
    StaircaseFieldsMixin,
    RentalPropertyFieldsMixin,
    MaintenanceUnitFieldsMixin,
    TenantFieldsMixin,
    LeaseFieldsMixin,
    ParkingSpaceFieldsMixin,
    FacilityFieldsMixin,
    models.Model,
):
    _inherit = "maintenance.request"
    _order = "recently_added_tenant desc, request_date desc"

    # ============================================================================
    # CORE FIELDS
    # ============================================================================

    uuid = fields.Char(
        string="UUID", default=lambda self: str(uuid.uuid4()), readonly=True, copy=False
    )

    # ============================================================================
    # REQUEST CONFIGURATION
    # ============================================================================

    maintenance_request_category_id = fields.Many2one(
        "maintenance.request.category",
        string="Ärendekategori",
        required=True,
        store=True,
    )
    start_date = fields.Date("Startdatum", store=True)
    hidden_from_my_pages = fields.Boolean(
        "Dold från Mimer.nu", store=True, default=False
    )

    space_caption = fields.Selection(
        selection=SORTED_SPACES,
        string="Utrymme",
        store=True,
        required=True,
    )
    equipment_code = fields.Char("Utrustningskod", store=True, readonly=True)
    master_key = fields.Boolean("Huvudnyckel", store=True)

    priority_expanded = fields.Selection(
        PRIORITY_OPTIONS,
        string="Prioritet",
        store=True,
    )
    due_date = fields.Date("Förfallodatum", compute="_compute_due_date", store=True)
    creation_origin = fields.Selection(
        CREATION_ORIGINS,
        string="Skapad från",
        default="internal",
        store=True,
    )

    # ============================================================================
    # MIMER.NU INTEGRATION FIELDS
    # ============================================================================

    pet = fields.Char("Husdjur", store=True)
    call_between = fields.Char("Nås mellan", store=True)
    hearing_impaired = fields.Boolean("Hörselnedsättning", store=True)
    space_code = fields.Char("Utrymmeskod", store=True)

    # ============================================================================
    # COMPUTED FIELDS
    # ============================================================================

    today_date = fields.Date(string="Today", compute="_compute_today_date", store=False)
    new_mimer_notification = fields.Boolean(
        string="New Mimer Message",
        compute="_compute_new_mimer_notification",
        store=False,
    )
    floor_plan_image = fields.Image(
        store=False, readonly=True, compute="_compute_floor_plan"
    )
    form_state = fields.Selection(FORM_STATES, compute="_compute_form_state")

    # ============================================================================
    # PERMISSION FIELDS
    # ============================================================================

    maintenance_team_domain = fields.Binary(
        string="Maintenance team domain", compute="_compute_maintenance_team_domain"
    )
    restricted_external = fields.Boolean(
        string="Restricted external contractors", compute="_compute_restricted_external"
    )
    user_is_external_contractor = fields.Boolean(
        string="User is external contractor",
        compute="_compute_user_is_external_contractor",
    )

    # ============================================================================
    # HELPER METHODS
    # ============================================================================

    def get_core_api(self):
        return core_api.CoreApi(self.env)

    # ============================================================================
    # COMPUTED FIELD METHODS
    # ============================================================================

    @api.depends(
        "space_caption",
    )
    def _compute_form_state(self):
        for record in self:
            if record.space_caption == "Bilplats":
                record.form_state = "parking-space"
            elif record.space_caption == "Fastighet":
                record.form_state = "property"
            elif record.space_caption in [
                "Byggnad",
                "Uppgång",
                "Vind",
                "Källare",
                "Cykelförråd",
                "Gården/Utomhus",
                "Övrigt",
            ]:
                record.form_state = "building"
            elif record.space_caption in [
                "Tvättstuga",
                "Miljöbod",
                "Lekplats",
            ]:
                record.form_state = "maintenance-unit"
            elif record.space_caption == "Lokal":
                record.form_state = "facility"
            elif record.space_caption in [
                "Lägenhet",
            ]:
                record.form_state = "rental-property"
            else:
                # Fallback for any undefined space_caption
                record.form_state = "rental-property"

    @api.depends("rental_property_id", "rental_property_option_id")
    def _compute_floor_plan(self):
        for record in self:
            id = (
                record.rental_property_id
                if record.rental_property_id
                else record.rental_property_option_id
            )

            if id and record.space_caption == "Lägenhet":
                url = f"https://pub.mimer.nu/bofaktablad/bofaktablad/{id.name}.jpg"
                response = requests.get(url)
                if response.status_code == 200:
                    record.floor_plan_image = base64.b64encode(response.content)
                else:
                    record.floor_plan_image = ""
            else:
                record.floor_plan_image = ""

    @api.depends("recently_added_tenant")
    def _compute_empty_tenant(self):
        record_service = RecordManagementService(self.env)
        for record in self:
            record_service.handle_empty_tenant_logic(record)

    @api.depends(
        "message_ids.notification_ids.is_read",
        "message_ids.notification_ids.notification_type",
    )
    def _compute_new_mimer_notification(self):
        for record in self:
            message_ids = record.message_ids.ids

            unread_mimer_notifications = self.env["mail.notification"].search(
                [
                    ("mail_message_id", "in", message_ids),
                    ("res_partner_id", "=", self.env.user.partner_id.id),
                    ("is_read", "!=", True),
                    ("notification_type", "=", "inbox"),
                    (
                        "mail_message_id.author_id.user_ids.login",
                        "=",
                        "odoo@mimer.nu",
                    ),
                ]
            )

            record.new_mimer_notification = len(unread_mimer_notifications.ids) > 0

    def _send_creation_sms(self):
        """Send SMS notification when maintenance request is created."""
        if not self.phone_number or self.hidden_from_my_pages:
            return

        mail_message = self.env["mail.message"]
        message = f"Hej {self.tenant_name}!\n\nTack för din serviceanmälan. Du kan följa, uppdatera och prata med oss om ditt ärende på Mina sidor."
        return mail_message._send_sms(self.phone_number, message)

    @api.depends("maintenance_team_id")
    def _compute_maintenance_team_domain(self):
        for record in self:
            if record.maintenance_team_id:
                ids = record.maintenance_team_id.member_ids.ids
                record.maintenance_team_domain = [("id", "in", ids)]

                if record.user_id.id not in ids:
                    record.user_id = False
            else:
                record.maintenance_team_domain = []

    @api.model
    def _compute_today_date(self):
        for record in self:
            record.today_date = fields.Date.context_today(self)

    def _compute_restricted_external(self):
        external_contractor_service = ExternalContractorService(self.env)
        for record in self:
            record.restricted_external = (
                external_contractor_service.get_restricted_status(record)
            )

    def _compute_user_is_external_contractor(self):
        external_contractor_service = ExternalContractorService(self.env)
        is_external = external_contractor_service.is_external_contractor()
        for record in self:
            record.user_is_external_contractor = is_external

    @api.depends("request_date", "start_date", "priority_expanded")
    def _compute_due_date(self):
        for record in self:
            base_date = record.start_date if record.start_date else record.request_date

            if base_date and record.priority_expanded:
                record.due_date = fields.Date.add(
                    base_date, days=int(record.priority_expanded)
                )

    # ============================================================================
    # UTILITY METHODS
    # ============================================================================

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        fields_to_hide = ["lease_number", "notice_given_by", "preferred_move_out_date"]
        res = super().fields_get(allfields, attributes)
        for field in fields_to_hide:
            if res.get(field):
                res[field]["searchable"] = False
        return res

    @api.model
    def fetch_tenant_contact_data(self, thread_id):
        record = self.env["maintenance.request"].search([("id", "=", thread_id)])

        def is_valid(value):
            return value not in [None, False, "", "redacted"]

        return {
            "has_email": is_valid(record.tenant_id.email_address),
            "has_phone_number": is_valid(record.tenant_id.phone_number),
        }

    @api.model
    def fetch_is_hidden_from_my_pages(self, thread_id):
        record = self.env["maintenance.request"].search([("id", "=", thread_id)])
        return {"hidden_from_my_pages": record.hidden_from_my_pages}

    # ============================================================================
    # SEARCH FUNCTIONALITY
    # ============================================================================

    @api.onchange("search_value", "search_type", "space_caption")
    def _compute_search(self):
        base_handler = BaseMaintenanceHandler(self, self.get_core_api())
        base_handler._delete_options()

        if not self.space_caption:
            return

        # Check if the search combination is supported
        if not HandlerFactory.is_combination_supported(
            self.search_type, self.space_caption
        ):
            return {
                "warning": {
                    "title": "Kombinationen stöds inte",
                    "message": f'Sökning med "{dict(SEARCH_TYPES).get(self.search_type, self.search_type)}" för utrymme "{self.space_caption}" stöds inte för tillfället. Välj en annan kombination av söktyp och utrymme.',
                }
            }

        if not self.search_value or not validators[self.search_type](self.search_value):
            return

        handler = HandlerFactory.get_handler(
            self, self.get_core_api(), self.search_type, self.space_caption
        )

        # if not self.search_value or not validators[self.search_type](self.search_value):
        #     handler._delete_options()
        #     return

        for record in self:
            handler.handle_search(
                record.search_type, record.search_value, record.space_caption
            )

    # ============================================================================
    # ONCHANGE METHODS
    # ============================================================================

    @api.onchange("property_option_id")
    def _onchange_property_option_id(self):
        field_manager = FormFieldService(self.env)
        for record in self:
            field_manager.update_property_fields(record)

    @api.onchange("building_option_id")
    def _onchange_building_option_id(self):
        field_manager = FormFieldService(self.env)
        for record in self:
            field_manager.update_building_fields(record)

    @api.onchange("staircase_option_id")
    def _onchange_staircase_option_id(self):
        field_manager = FormFieldService(self.env)
        for record in self:
            field_manager.update_staircase_fields(record)

    @api.onchange("rental_property_option_id")
    def _onchange_rental_property_option_id(self):
        field_manager = FormFieldService(self.env)
        for record in self:
            field_manager.update_rental_property_fields(record)

    @api.onchange("maintenance_unit_option_id")
    def _onchange_maintenance_unit_option_id(self):
        field_manager = FormFieldService(self.env)
        for record in self:
            field_manager.update_maintenance_unit_fields(record)

    @api.onchange("lease_option_id")
    def _onchange_lease_option_id(self):
        field_manager = FormFieldService(self.env)
        for record in self:
            field_manager.update_lease_fields(record)

    @api.onchange("tenant_option_id")
    def _onchange_tenant_option_id(self):
        field_manager = FormFieldService(self.env)
        for record in self:
            field_manager.update_tenant_fields(record)

    @api.onchange("parking_space_option_id")
    def _onchange_parking_space_option_id(self):
        field_manager = FormFieldService(self.env)
        for record in self:
            field_manager.update_parking_space_fields(record)

    @api.onchange("facility_option_id")
    def _onchange_facility_option_id(self):
        field_manager = FormFieldService(self.env)
        for record in self:
            field_manager.update_facility_fields(record)

    # ============================================================================
    # CRUD OPERATIONS
    # ============================================================================

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info(f"Creating maintenance requests: {vals_list}")

        images = []
        for vals in vals_list:
            if "images" in vals:
                images.append(vals.pop("images"))
            else:
                images.append([])

            # if not vals.get("space_caption"):
            #     vals["space_caption"] = "Tvättstuga"

        maintenance_requests = super(
            OneCoreMaintenanceRequest, self.with_context(creating_records=True)
        ).create(vals_list)

        create_service = RecordManagementService(self.env)
        stage_manager = MaintenanceStageManager(self.env)

        for idx, request in enumerate(maintenance_requests):
            vals = vals_list[idx]

            create_service.create_related_records(request, vals)

            if images[idx]:
                create_service.handle_images(request, images[idx])

            # Add followers if users are assigned
            if request.owner_user_id or request.user_id:
                request._add_followers()

            create_service.setup_team_assignment(request)
            create_service.setup_close_date(request)
            stage_manager.handle_initial_user_assignment(request)

            request._send_creation_sms()

        maintenance_requests.activity_update()

        return maintenance_requests

    def write(self, vals):
        if self.env.context.get("creating_records"):
            return super().write(vals)

        stage_manager = MaintenanceStageManager(self.env)
        external_contractor_service = ExternalContractorService(self.env)

        # Handle stage transitions
        if "stage_id" in vals:
            external_contractor_service.validate_stage_transition(
                self, vals["stage_id"]
            )
            stage_manager.handle_stage_change(self, vals["stage_id"])

        # Handle resource assignment workflow
        if "user_id" in vals:
            workflow_updates = stage_manager.handle_resource_assignment(
                self, vals.get("user_id")
            )
            vals.update(workflow_updates)

        change_tracker = FieldChangeTracker(self.env)
        changes_by_record = change_tracker.track_field_changes(self, vals)

        result = super().write(vals)

        change_tracker.post_change_notifications(self, changes_by_record)

        return result

    # ============================================================================
    # INTEGRATION METHODS
    # ============================================================================

    def open_time_report(self):
        self.ensure_one()
        estate_code = False
        if self.rental_property_id and self.rental_property_id.estate_code:
            estate_code = self.rental_property_id.estate_code
        elif self.maintenance_unit_id and self.maintenance_unit_id.estate_code:
            estate_code = self.maintenance_unit_id.estate_code

        base_url = self.env["ir.config_parameter"].get_param(
            "time_report_base_url",
            "https://apps.mimer.nu/version-test/tidsrapportering/",
        )

        url = base_url
        params = {"od": self.id}
        if estate_code:
            params["p"] = estate_code
        url = f"{base_url}?{urllib.parse.urlencode(params)}"

        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "self",
        }
