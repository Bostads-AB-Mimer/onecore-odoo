import urllib.parse
import uuid
import logging
import json
import time

from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ...onecore_api import core_api
from .handlers import HandlerFactory, BaseMaintenanceHandler
from .utils import validators
from .services import (
    FieldChangeTracker,
    RecordManagementService,
    FormFieldService,
    ExternalContractorService,
    MaintenanceStageManager,
    ManagementAreaService,
)
from .constants import (
    SORTED_SPACES,
    SEARCH_TYPES,
    PRIORITY_OPTIONS,
    CREATION_ORIGINS,
    FORM_STATES,
    CUSTOMER_MESSAGE_TYPE,
    RECEIPT_TO_TENANT_MESSAGE_TYPE,
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

# Per-worker cache so the pest control badge doesn't trigger a OneCore call on
# every form read (web_save re-reads included). Worst-case staleness = TTL.
PEST_CONTROL_CACHE_TTL = 300  # seconds
_pest_control_cache = {}  # rental_id -> (expires_at_monotonic, bool)


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
    # Customer messages first — "ska sorteras högst upp i kanban vyn". _order
    # takes stored columns only, hence the stored customer_message_unread
    # boolean rather than the non-stored has_unread_customer_message.
    _order = (
        "customer_message_unread desc, " "recently_added_tenant desc, request_date desc"
    )
    _unaccent = True

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
    performed_date = fields.Datetime("Utförd datum", store=True, readonly=True)
    closed_date = fields.Datetime("Avslutad datum", store=True, readonly=True)
    returned_date = fields.Datetime("Återsänd datum", store=True, readonly=True)
    hidden_from_my_pages = fields.Boolean(
        "Dold från Mimer.nu", store=True, default=False
    )

    has_loan_product = fields.Boolean(
        "Låneprodukt utlämnad",
        store=True,
        default=False,
        help="Indikerar om en låneprodukt har lämnats ut till kunden",
    )
    loan_product_details = fields.Char(
        "Detaljer låneprodukt",
        store=True,
        help="Beskrivning av vilken produkt som lämnats ut",
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
    due_date = fields.Date(
        "Förfallodatum",
        compute="_compute_due_date",
        inverse="_inverse_due_date",
        store=True,
        readonly=False,
    )
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
    schedule_date_date = fields.Date(
        string="Planerat utförandedatum",
        compute="_compute_schedule_date_date",
        store=False,
    )
    schedule_date_after_due_date = fields.Boolean(
        string="Planerat utförandedatum efter förfallodatum",
        compute="_compute_schedule_date_after_due_date",
        store=False,
    )
    supplier_dialog_ack_at = fields.Datetime(
        string="Mimer har bekräftat att de läst meddelandet",
        help="Senaste tidpunkt en Mimer-handläggare kvitterade entreprenörens noteringar.",
    )
    internal_dialog_ack_at = fields.Datetime(
        string="Leverantören bekräftar att de läst meddelandet",
        help="Senaste tidpunkt en entreprenör kvitterade Mimers noteringar.",
    )
    has_unread_supplier_dialog = fields.Boolean(
        string="Olästa meddelanden från leverantör",
        compute="_compute_dialog_indicators",
        store=False,
    )
    has_unread_internal_dialog = fields.Boolean(
        string="Olästa meddelanden från Mimer",
        compute="_compute_dialog_indicators",
        store=False,
    )
    master_key_changed_at = fields.Datetime(
        string="Huvudnyckel senast ändrad",
        help="Sätts automatiskt när fältet Huvudnyckel ändras efter att ärendet skapats.",
    )
    master_key_ack_at = fields.Datetime(
        string="Huvudnyckeländring kvitterad",
        help="Senaste tidpunkt någon kvitterade ändring av huvudnyckel. Delas av alla användare som har tillgång till ärendet.",
    )
    has_unread_master_key_change = fields.Boolean(
        string="Okvitterad huvudnyckeländring",
        compute="_compute_has_unread_master_key_change",
        store=False,
    )
    customer_message_ack_at = fields.Datetime(
        string="Meddelande från kund kvitterat",
        help="Senaste tidpunkt någon kvitterade ett meddelande från kund. "
        "Delas av alla användare — Mimer-handläggare och externa "
        "entreprenörer — som har tillgång till ärendet (MIM-1960).",
    )
    has_unread_new_customer_info = fields.Boolean(
        string="Okvitterad ny kundinfo",
        compute="_compute_has_unread_new_customer_info",
        store=False,
    )
    last_customer_message_at = fields.Datetime(
        string="Senaste meddelande från kund",
        help="Sätts automatiskt när ett meddelande från kund kommer in via "
        "Mina sidor. Driver sorteringen i kanbanvyn.",
    )
    # Stored, so _order can promote requests with an outstanding customer
    # message — a non-stored computed field cannot be ordered on. Shared
    # across audiences (MIM-1960): one boolean, not one per side.
    customer_message_unread = fields.Boolean(
        string="Okvitterat kundmeddelande",
        compute="_compute_customer_message_unread",
        store=True,
    )
    has_unread_customer_message = fields.Boolean(
        string="Okvitterat meddelande från kund",
        compute="_compute_has_unread_customer_message",
        store=False,
    )
    # Form-view only. Adding this to tree/kanban would fire one API call per row.
    requires_pest_control = fields.Boolean(
        string="Spärr skadedjur",
        compute="_compute_requires_pest_control",
        store=False,
    )
    floor_plan_image_url = fields.Char(
        store=False, readonly=True, compute="_compute_floor_plan"
    )
    form_state = fields.Selection(FORM_STATES, compute="_compute_form_state")

    # ============================================================================
    # MANAGEMENT AREA — distrikt / kvartersvärdsområde (OneCore snapshot)
    # ============================================================================
    # Written on the write path only (create, "Tilldela resursgrupp", backfill
    # cron) by ManagementAreaService — never computed on read (MIM-1869).
    # kvv_area_name can be empty in OneCore and captions are not unique:
    # group and pair on the codes, show the names as labels.
    kvv_area_code = fields.Char("Kvartersvärdsområde (kod)", readonly=True)
    kvv_area_name = fields.Char("Kvartersvärdsområde (namn)", readonly=True)
    kvv_area_display = fields.Char(
        "Kvartersvärdsområde", compute="_compute_kvv_area_display"
    )
    cost_center_code = fields.Char("Distrikt (kod)", readonly=True)
    cost_center_name = fields.Char("Distrikt (namn)", readonly=True)
    cost_center_display = fields.Char(
        "Tillhör distrikt", compute="_compute_cost_center_display"
    )
    district_manager = fields.Char(
        "Distriktschef",
        compute="_compute_district_manager",
        help="Kontakta i första hand ärendets resurs.",
    )
    # Deliberately NOT stored on the request: resolved from the local
    # maintenance.kvv.area master (cron-synced), so vikarie/steward changes in
    # OneCore show up everywhere without touching requests. DB-only compute.
    kvv_area_responsible = fields.Char(
        "Nuvarande kvartersvärd",
        compute="_compute_kvv_area_responsible",
        # Escalation ladder: resurs -> kvartersvärd -> distriktschef. The
        # kvartersvärd is not the one handling the request, so say who is.
        # Defined on the field, not in the view: it applies to all six
        # Objektsinformation groups and the list column at once.
        help="Kontakta i första hand ärendets resurs.",
    )
    management_area_lookup_at = fields.Datetime(
        "Distrikt uppslaget",
        readonly=True,
        help="Senaste lyckade uppslag av distrikt/kvartersvärdsområde i OneCore "
        "(även när fastigheten saknar koppling). Tomt = aldrig uppslaget eller "
        "misslyckat — backfill-jobbet försöker igen.",
    )

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

    @api.depends("kvv_area_code", "kvv_area_name")
    def _compute_kvv_area_display(self):
        # MIM-1967: the code is what users work with ("61112"). OneCore's
        # captions are not unique (61111/61112 share one) and grouping already
        # runs on the code, so showing the code keeps display and grouping
        # consistent. Name is kept as a fallback only.
        for record in self:
            record.kvv_area_display = (
                record.kvv_area_code or record.kvv_area_name or False
            )

    @api.depends("cost_center_code", "cost_center_name")
    def _compute_cost_center_display(self):
        # Same format as property-tree's dropdown: "61110 - Distrikt Mitt"
        for record in self:
            if record.cost_center_code and record.cost_center_name:
                record.cost_center_display = (
                    f"{record.cost_center_code} - {record.cost_center_name}"
                )
            else:
                record.cost_center_display = (
                    record.cost_center_code or record.cost_center_name or False
                )

    @api.depends("cost_center_code")
    def _compute_district_manager(self):
        """Escalation step 3, from the nightly-synced cost-center master.

        Hidden when OneCore has no chef for the district — an empty row would
        be worse than none. Batched, like the kvartersvärd."""
        codes = {record.cost_center_code for record in self if record.cost_center_code}
        by_code = {}
        if codes:
            districts = (
                self.env["maintenance.cost.center"]
                .sudo()
                .search([("code", "in", list(codes))])
            )
            by_code = {district.code: district for district in districts}
        for record in self:
            district = by_code.get(record.cost_center_code)
            lead = district.lead_name if district else False
            deputy = district.deputy_name if district else False
            if lead and deputy and lead != deputy:
                record.district_manager = f"{lead} (bitr. {deputy})"
            elif lead:
                # Mimer Student has no deputy, and test data can point both
                # roles at the same person — show the name once either way
                record.district_manager = lead
            elif deputy:
                record.district_manager = f"{deputy} (bitr.)"
            else:
                record.district_manager = False

    @api.depends("kvv_area_code")
    def _compute_kvv_area_responsible(self):
        # One batched lookup in the local master — no HTTP on read (MIM-1869)
        codes = {record.kvv_area_code for record in self if record.kvv_area_code}
        by_code = {}
        if codes:
            areas = (
                self.env["maintenance.kvv.area"]
                .sudo()
                .search([("code", "in", list(codes))])
            )
            by_code = {area.code: area.responsible_name for area in areas}
        for record in self:
            if record.kvv_area_code not in by_code:
                # No master row: the sync has not run yet (fresh install, or
                # OneCore was down at 03:00). Hide the row rather than claim
                # the area has no steward.
                record.kvv_area_responsible = False
            else:
                # "–" when the area is known but has no steward right now
                record.kvv_area_responsible = by_code[record.kvv_area_code] or "–"

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

    @api.depends("rental_property_id", "rental_property_option_id", "space_caption")
    def _compute_floor_plan(self):
        # No HTTP here: the browser loads the image via the image_viewer widget.
        for record in self:
            id = (
                record.rental_property_id
                if record.rental_property_id
                else record.rental_property_option_id
            )

            if id and record.space_caption == "Lägenhet":
                record.floor_plan_image_url = (
                    f"https://pub.mimer.nu/bofaktablad/bofaktablad/{id.name}.jpg"
                )
            else:
                record.floor_plan_image_url = False

    @api.depends("recently_added_tenant")
    def _compute_empty_tenant(self):
        record_service = RecordManagementService(self.env)
        for record in self:
            record_service.handle_empty_tenant_logic(record)

    @api.depends("rental_property_id", "rental_property_option_id")
    def _compute_requires_pest_control(self):
        api = None
        for record in self:
            rental_id = None
            if record.rental_property_id:
                rental_id = record.rental_property_id.rental_property_id
            elif record.rental_property_option_id:
                rental_id = record.rental_property_option_id.name

            if not rental_id:
                record.requires_pest_control = False
                continue

            cached = _pest_control_cache.get(rental_id)
            if cached and time.monotonic() < cached[0]:
                record.requires_pest_control = cached[1]
                continue

            try:
                if api is None:
                    api = record.get_core_api()
                data = api.fetch_residence(rental_id, timeout=5)
                blocks = (data or {}).get("propertyObject", {}).get(
                    "rentalBlocks"
                ) or []
                value = any((b or {}).get("blockReason") == "SKADEDJUR" for b in blocks)
                _pest_control_cache[rental_id] = (
                    time.monotonic() + PEST_CONTROL_CACHE_TTL,
                    value,
                )
                record.requires_pest_control = value
            except Exception as err:
                _logger.warning(
                    "Could not fetch pest control status for rental_id %s: %s",
                    rental_id,
                    err,
                )
                record.requires_pest_control = False

    @api.depends(
        "message_ids.date",
        "message_ids.author_id",
        "message_ids.message_type",
        "message_ids.subtype_id",
        "message_ids.informs_opposite_party",
        "supplier_dialog_ack_at",
        "internal_dialog_ack_at",
    )
    def _compute_dialog_indicators(self):
        # Bidirectional orange-chip for the log-note dialog between internal
        # Mimer handlers and external contractors. The classification rules
        # live in _dialog_unread_message_ids (shared with mail.message).
        for record in self:
            record.has_unread_supplier_dialog = False
            record.has_unread_internal_dialog = False

        if not self:
            return

        note_subtype = self.env.ref("mail.mt_note", raise_if_not_found=False)
        if not note_subtype:
            return

        messages = self.env["mail.message"].search(
            [
                ("model", "=", "maintenance.request"),
                ("res_id", "in", self.ids),
                ("message_type", "=", "comment"),
                ("subtype_id", "=", note_subtype.id),
                ("author_id", "!=", False),
                ("informs_opposite_party", "=", True),
            ]
        )
        unread_ids = self._dialog_unread_message_ids(messages)
        if not unread_ids:
            return

        # Pick the indicator for the viewing side: an internal handler only
        # ever sees supplier notes, an external contractor only ever sees
        # Mimer notes.
        is_external = ExternalContractorService(self.env).is_external_contractor()
        indicator_field = (
            "has_unread_internal_dialog"
            if is_external
            else "has_unread_supplier_dialog"
        )
        unread_res_ids = set(
            messages.filtered(lambda m: m.id in unread_ids).mapped("res_id")
        )
        for record in self:
            if record.id in unread_res_ids:
                record[indicator_field] = True

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        # Stored so _order can promote the request — a per-user computed field
        # cannot be ordered on. sudo() because the poster is the work-order
        # service's integration account, which need not hold write access on
        # every field of the request.
        if message.message_type == CUSTOMER_MESSAGE_TYPE:
            # Only ever advance the anchor. A from_tenant message can in
            # principle be posted with a backdated date (an import, a replay);
            # assigning unconditionally would then move the anchor below an
            # existing acknowledgement and silently swallow a newer, genuinely
            # unread message.
            if not self.last_customer_message_at or (
                message.date > self.last_customer_message_at
            ):
                self.sudo().write({"last_customer_message_at": message.date})
        return message

    def _get_allowed_message_params(self):
        # Let the chatter composer flag a log note as "inform the opposite
        # party" through /mail/message/post; without this the controller drops
        # the key before it reaches message_post (see the mail.message field).
        return super()._get_allowed_message_params() | {"informs_opposite_party"}

    def _get_message_create_valid_field_names(self):
        # message_post() -> _message_create() validates the message values
        # against this allow-list; our custom field must be added or posting a
        # note with informs_opposite_party raises ValueError.
        return super()._get_message_create_valid_field_names() | {
            "informs_opposite_party"
        }

    @api.model
    def _dialog_unread_message_ids(self, messages):
        """Return the ids of ``messages`` that are unread dialog notes for the
        side the current user belongs to (Mimer handlers vs external
        contractors).

        A message counts when it is a log note (``mail.mt_note`` comment) on a
        maintenance.request that its author flagged with
        ``informs_opposite_party``, authored by the *opposite* side, and posted
        after that side last acknowledged the dialog. Acknowledgement is a
        single per-side timestamp on the request, so one staffer marking it
        read clears it for everyone on their side. The current user only selects
        which side's view to compute; this is not per-user read state. Shared
        by ``_compute_dialog_indicators`` and
        ``mail.message._compute_is_dialog_unread_for_side`` so the rules live
        in exactly one place.
        """
        # Cheap structural pre-filter before any ref lookups. Only notes the
        # author flagged "inform the opposite party" count.
        candidates = messages.filtered(
            lambda m: m.model == "maintenance.request"
            and m.message_type == "comment"
            and m.author_id
            and m.res_id
            and m.informs_opposite_party
        )
        if not candidates:
            return set()

        external_group = self.env.ref(
            "onecore_maintenance_extension.group_external_contractor",
            raise_if_not_found=False,
        )
        note_subtype = self.env.ref("mail.mt_note", raise_if_not_found=False)
        if not external_group or not note_subtype:
            return set()

        candidates = candidates.filtered(lambda m: m.subtype_id.id == note_subtype.id)
        if not candidates:
            return set()

        is_external = ExternalContractorService(self.env).is_external_contractor()
        ack_field = (
            "internal_dialog_ack_at" if is_external else "supplier_dialog_ack_at"
        )

        # Per-request acknowledgement timestamp.
        request_ids = list(set(candidates.mapped("res_id")))
        ack_by_request = {req.id: req[ack_field] for req in self.browse(request_ids)}

        # Classify message authors as external. sudo() so correctness does not
        # depend on whether the requesting user may read other users' groups.
        author_partner_ids = list(set(candidates.mapped("author_id").ids))
        external_users = (
            self.env["res.users"]
            .sudo()
            .search(
                [
                    ("partner_id", "in", author_partner_ids),
                    ("all_group_ids", "in", external_group.id),
                ]
            )
        )
        external_partner_ids = set(external_users.mapped("partner_id").ids)

        unread_ids = set()
        for message in candidates:
            author_is_external = message.author_id.id in external_partner_ids
            # Only the opposite party's notes count.
            if is_external == author_is_external:
                continue
            ack_at = ack_by_request.get(message.res_id)
            # Second-resolution edge: a note posted in the same second as the
            # acknowledgement is treated as read (<=). A sub-second race between
            # two different human users is negligible in practice.
            if ack_at and message.date and message.date <= ack_at:
                continue
            unread_ids.add(message.id)
        return unread_ids

    @api.depends("master_key_changed_at", "master_key_ack_at")
    def _compute_has_unread_master_key_change(self):
        # One shared ack timestamp — first user from any side to click
        # "Markera som läst" clears the chip for everyone with access to the
        # request (external contractors, equipment managers, internal staff).
        for record in self:
            if not record.master_key_changed_at:
                record.has_unread_master_key_change = False
                continue
            ack_at = record.master_key_ack_at
            record.has_unread_master_key_change = (
                not ack_at or record.master_key_changed_at > ack_at
            )

    @api.depends("recently_added_tenant")
    @api.depends_context("uid")
    def _compute_has_unread_new_customer_info(self):
        # "Ny kundinfo" now means exactly what the name says: the customer's
        # *information* was updated. The tenant was back-filled from the OneCore
        # API — a Mimer data-quality flag, not tenant communication, so it never
        # reaches external contractors. Tenant messages moved to
        # has_unread_customer_message (MIM-1960).
        is_external = ExternalContractorService(self.env).is_external_contractor()
        for record in self:
            record.has_unread_new_customer_info = (
                False if is_external else record.recently_added_tenant
            )

    @api.depends("last_customer_message_at", "customer_message_ack_at")
    def _compute_customer_message_unread(self):
        # Stored, so no depends_context: one shared fact, not one per
        # audience (MIM-1960) — the first acknowledger from either side
        # silences it for everyone.
        for record in self:
            latest = record.last_customer_message_at
            ack = record.customer_message_ack_at
            record.customer_message_unread = bool(latest) and (not ack or latest > ack)

    @api.depends("customer_message_unread")
    def _compute_has_unread_customer_message(self):
        # Non-stored mirror of the stored boolean — kept as a separate field
        # (rather than having views/JS read customer_message_unread directly)
        # so the name views and JS already use needs no changes.
        for record in self:
            record.has_unread_customer_message = record.customer_message_unread

    def action_acknowledge_dialog(self):
        """Mark the log-note dialog read for the acking user's whole side.

        Acknowledgement is stored as one timestamp per side on the request, so
        every staffer on that side (all Mimer handlers, or all external
        contractors) shares it — one person marking read clears the chip and
        the highlight for the whole side.
        """
        self.ensure_one()
        now = fields.Datetime.now()
        if ExternalContractorService(self.env).is_external_contractor():
            self.internal_dialog_ack_at = now
        else:
            self.supplier_dialog_ack_at = now
        # Non-stored computed fields don't invalidate automatically when the
        # stored ack field is written — force a recompute so the chatter button
        # and the kanban chip re-evaluate immediately.
        self.invalidate_recordset(
            ["has_unread_supplier_dialog", "has_unread_internal_dialog"]
        )
        self.env["mail.message"].invalidate_model(["is_dialog_unread_for_side"])
        return True

    def action_acknowledge_customer_message(self):
        """Mark the tenant's Mina-sidor message read for everyone (MIM-1960).

        One shared timestamp: the first person to acknowledge — from either
        Mimer or an external contractor's side — silences the status for
        both. The no-op guard below is what stops a second acknowledger: by
        the time anyone else clicks, has_unread_customer_message is already
        False, so reaching the write below means the acking user is first,
        and posting the receipt unconditionally there is correct — no
        "other side" guard is needed any more.
        """
        self.ensure_one()
        if not self.has_unread_customer_message:
            return True
        now = fields.Datetime.now()
        is_external = ExternalContractorService(self.env).is_external_contractor()
        self.customer_message_ack_at = now
        self._post_customer_message_receipt(is_external)
        # Non-stored computed field — writing the stored ack does not invalidate
        # it automatically, so force a recompute for the chatter button and the
        # kanban chip.
        self.invalidate_recordset(["has_unread_customer_message"])
        return True

    def _post_customer_message_receipt(self, is_external):
        """Confirm to the tenant that their message was read.

        Lands in the Odoo händelselogg immediately, and on Mina sidor once
        receipt_to_tenant is allowlisted in the work-order service's
        MESSAGE_DOMAIN — that is a read filter, so earlier receipts appear
        retroactively.

        Posted as the acking user, so the audit log records who acknowledged.
        Mina sidor shows only a first name beside the body, and the body carries
        the organisation name the tenant needs.
        """
        self.ensure_one()
        sender = "Mimer"
        if is_external and self.maintenance_team_id:
            sender = self.maintenance_team_id.name
        return self.message_post(
            body=f"{sender} har mottagit ditt meddelande",
            message_type=RECEIPT_TO_TENANT_MESSAGE_TYPE,
            subtype_xmlid="mail.mt_note",
        )

    def action_acknowledge_master_key_change(self):
        """Mark the master-key change read for every viewer of the request.

        Acknowledgement is one timestamp per request, shared by everyone with
        access — the first user to click "Markera som läst" (external
        contractor, equipment manager, or internal handler) clears the chip
        and the chatter button for the whole audience.
        """
        self.ensure_one()
        self.master_key_ack_at = fields.Datetime.now()
        # Non-stored computed field — force a recompute so the chatter button
        # and the kanban chip re-evaluate immediately.
        self.invalidate_recordset(["has_unread_master_key_change"])
        return True

    def action_acknowledge_new_customer_info(self):
        """Clear the "Ny kundinfo" flag for every Mimer user on the request.

        There is no timestamp: the signal *is* recently_added_tenant, so
        clearing the flag is the acknowledgement. Internal only — the flag also
        drives _order for everyone, and contractors never see the badge.
        """
        self.ensure_one()
        if ExternalContractorService(self.env).is_external_contractor():
            return True
        if self.recently_added_tenant:
            self.recently_added_tenant = False
        self.invalidate_recordset(["has_unread_new_customer_info"])
        return True

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
            else:
                record.maintenance_team_domain = []

    @api.model
    def _compute_today_date(self):
        for record in self:
            record.today_date = fields.Date.context_today(self)

    @api.depends("schedule_date")
    def _compute_schedule_date_date(self):
        for record in self:
            if record.schedule_date:
                record.schedule_date_date = fields.Datetime.context_timestamp(
                    record, record.schedule_date
                ).date()
            else:
                record.schedule_date_date = False

    @api.depends("schedule_date_date", "due_date")
    def _compute_schedule_date_after_due_date(self):
        # Compares calendar dates, not timestamps: schedule_date is a Datetime
        # and due_date a Date, so a time of day on the due date itself must not
        # count as a breach. schedule_date_date already resolves the timezone.
        for record in self:
            record.schedule_date_after_due_date = bool(
                record.schedule_date_date
                and record.due_date
                and record.schedule_date_date > record.due_date
            )

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

    def _inverse_due_date(self):
        # Presence of this inverse lets the stored computed field retain
        # values supplied by the user; without it the recompute on flush
        # overwrites manual edits to förfallodatum.
        pass

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

    @api.model
    def is_user_external_contractor(self):
        """Check if current user is an external contractor - callable from RPC."""
        external_contractor_service = ExternalContractorService(self.env)
        return external_contractor_service.is_external_contractor()

    # ============================================================================
    # SEARCH FUNCTIONALITY
    # ============================================================================

    @api.onchange("search_value", "search_type", "space_caption")
    def _compute_search(self):
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

        # Preserve search values before deleting options - they get cleared by
        # onchange cascade, which leads to very clunky UX.
        saved_search_value = self.search_value
        saved_search_type = self.search_type
        saved_space_caption = self.space_caption
        saved_name = self.name
        saved_description = self.description

        # Only delete old options when we're about to perform a valid search.
        base_handler = BaseMaintenanceHandler(self, self.get_core_api())
        base_handler._delete_options()

        # Restore search values after deletion.
        self.search_value = saved_search_value
        self.search_type = saved_search_type
        self.space_caption = saved_space_caption
        if saved_name:
            self.name = saved_name
        if saved_description:
            self.description = saved_description

        handler = HandlerFactory.get_handler(
            self, self.get_core_api(), self.search_type, self.space_caption
        )

        if not handler:
            return

        for record in self:
            result = handler.handle_search(
                record.search_type, record.search_value, record.space_caption
            )
            # If handler returns a warning, propagate it to the UI
            if result and isinstance(result, dict) and result.get("warning"):
                return result

        # After search, check if a specific maintenance unit was requested via URL context.
        # Check both direct context (Odoo 19 client action path) and params.context
        # (legacy URL parameter path) for the maintenance unit code.
        url_context = {}
        params = self.env.context.get("params", {})
        if "context" in params and isinstance(params["context"], str):
            try:
                url_context = json.loads(params["context"])
            except (json.JSONDecodeError, TypeError):
                pass

        mu_code = self.env.context.get(
            "default_maintenance_unit_code"
        ) or url_context.get("default_maintenance_unit_code")

        if mu_code:
            unit = self.env["maintenance.maintenance.unit.option"].search(
                [
                    ("code", "=", mu_code),
                    ("user_id", "=", self.env.user.id),
                ],
                limit=1,
            )
            if unit:
                self.maintenance_unit_option_id = unit

    # ============================================================================
    # ONCHANGE METHODS
    # ============================================================================

    @api.onchange(
        "rental_property_option_id",
        "property_option_id",
        "building_option_id",
        "parking_space_option_id",
        "facility_option_id",
    )
    def _onchange_management_area_preview(self):
        """Show "Tillhör distrikt" already before the request is saved.

        Runs on the search/selection path (which already calls OneCore), never
        on read — see MIM-1869. Cached per property code, and create() re-reads
        the same cache, so picking a search hit costs at most one extra call.
        """
        service = ManagementAreaService(self.env)
        for record in self:
            service.preview(record)

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

    @api.onchange("user_id")
    def _onchange_user_id(self):
        stage_manager = MaintenanceStageManager(self.env)
        for record in self:
            updates = stage_manager.handle_resource_assignment(
                record, record.user_id.id if record.user_id else False
            )
            if "stage_id" in updates:
                record.stage_id = updates["stage_id"]

    @api.onchange("maintenance_team_id")
    def _onchange_maintenance_team_id(self):
        # Clear an assignee who is not a member of the newly selected team.
        # This is UI-only: it must never run from a compute (i.e. on read),
        # since user_id is stored and writing it would mutate the record and
        # break web_read. See _compute_maintenance_team_domain.
        for record in self:
            if record.maintenance_team_id and record.user_id:
                member_ids = record.maintenance_team_id.member_ids.ids
                if record.user_id.id not in member_ids:
                    record.user_id = False

    # ============================================================================
    # CRUD OPERATIONS
    # ============================================================================

    @api.model
    def default_get(self, fields_list):
        """Override to handle context values for pre-filling form fields."""

        defaults = super(OneCoreMaintenanceRequest, self).default_get(fields_list)

        # Parse context from params if it exists (for URL parameters)
        url_context = {}
        params = self.env.context.get("params", {})
        if "context" in params and isinstance(params["context"], str):
            try:
                url_context = json.loads(params["context"])
                _logger.info(f"Parsed URL context: {url_context}")
            except (json.JSONDecodeError, TypeError) as e:
                _logger.warning(f"Failed to parse context from params: {e}")

        # Handle search_type - check both direct context and URL context
        search_type = self.env.context.get("default_search_type") or url_context.get(
            "default_search_type"
        )
        if search_type:
            defaults["search_type"] = search_type

        # Handle search_value - check both direct context and URL context
        search_value = self.env.context.get("default_search_value") or url_context.get(
            "default_search_value"
        )
        if search_value:
            _logger.info(f"Setting search_value to: {search_value}")
            defaults["search_value"] = search_value

        # Handle space_caption - check both direct context and URL context
        space_caption = self.env.context.get(
            "default_space_caption"
        ) or url_context.get("default_space_caption")
        if space_caption:
            defaults["space_caption"] = space_caption

        return defaults

    def _web_read_group_format(self, groupby, aggregates, groups):
        result = super()._web_read_group_format(groupby, aggregates, groups)
        # MIM-486: the Återsänd kanban column is folded only while it is empty.
        # web_read_group folds groups based on the __fold flag stamped here.
        if groupby and groupby[0] == "stage_id":
            atersand = MaintenanceStageManager(self.env)._get_atersand_stage()
            if atersand:
                for dict_group in result:
                    # The m2o groupby value is (id, display_name) or False
                    value = dict_group.get("stage_id")
                    if (
                        value
                        and value[0] == atersand.id
                        and "__fold" in dict_group
                        and "__count" in dict_group
                    ):
                        dict_group["__fold"] = not dict_group["__count"]
                        break
        return result

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

        # Extract transient option fields before create — they are needed
        # for create_related_records but must not be cached by the ORM
        # (Odoo 19 web_read would try to resolve deleted option records)
        _option_fields = {
            "property_option_id",
            "building_option_id",
            "rental_property_option_id",
            "maintenance_unit_option_id",
            "tenant_option_id",
            "lease_option_id",
            "parking_space_option_id",
            "facility_option_id",
            "staircase_option_id",
        }
        option_vals_list = []
        for vals in vals_list:
            option_vals_list.append({f: vals.pop(f, False) for f in _option_fields})

        # Create maintenance requests
        # Note: activity_update() is overridden to suppress automatic activities
        maintenance_requests = super(
            OneCoreMaintenanceRequest, self.with_context(creating_records=True)
        ).create(vals_list)

        create_service = RecordManagementService(self.env)
        stage_manager = MaintenanceStageManager(self.env)
        management_area_service = ManagementAreaService(self.env)

        for idx, request in enumerate(maintenance_requests):
            vals = {**vals_list[idx], **option_vals_list[idx]}

            create_service.create_related_records(request, vals)

            if images[idx]:
                create_service.handle_images(request, images[idx])

            # Add followers if users are assigned
            if request.owner_user_id or request.user_id:
                request._add_followers()

            create_service.setup_team_assignment(request)
            # Snapshot distrikt / kvartersvärdsområde from OneCore. Best
            # effort (never blocks creation); skipped when the caller already
            # stamped the fields (core does for mimer.nu requests).
            management_area_service.populate(request)
            create_service.setup_close_date(request)
            stage_manager.handle_initial_user_assignment(request)

            request._send_creation_sms()

            # Post loan product message if loan product was issued during creation
            if vals.get("has_loan_product") and vals.get("loan_product_details"):
                request._post_loan_product_messages(
                    {
                        request.id: f"Låneprodukt utlämnad: {vals['loan_product_details']}"
                    }
                )

        # Note: The parent's create() method calls activity_update(), which we've
        # overridden to suppress all automatic maintenance activity creation
        return maintenance_requests

    def write(self, vals):
        # Check if we're in the initial creation phase
        skip_tracking = self.env.context.get("creating_records")

        stage_manager = MaintenanceStageManager(self.env)
        external_contractor_service = ExternalContractorService(self.env)

        # Handle stage transitions (always validate, even during creation)
        if "stage_id" in vals:
            external_contractor_service.validate_stage_transition(
                self, vals["stage_id"]
            )
            stage_updates = stage_manager.handle_stage_change(
                self, vals["stage_id"], vals
            )
            vals.update(stage_updates)

        # MIM-486: entering Återsänd clears the assigned resource and hands the
        # request back to the orderer's team. The team switch happens after
        # super().write() + notifications (see below), since the write may be
        # performed by an external contractor whose record-rule access depends
        # on the team.
        # Guarded on an actual stage change: a redundant write of the same
        # stage must not wipe a newly assigned resource or re-run the handback
        entering_atersand = (
            "stage_id" in vals
            and stage_manager.is_atersand_stage(vals["stage_id"])
            and any(record.stage_id.id != vals["stage_id"] for record in self)
        )
        if entering_atersand:
            vals["user_id"] = False
            if external_contractor_service.is_external_contractor():
                # Keep the returning contractor's access after the team
                # switch. web_save re-reads the record in the same
                # transaction; without follower access the read raises
                # AccessError and rolls back the whole return.
                self.sudo().message_subscribe(partner_ids=self.env.user.partner_id.ids)

        # Handle resource assignment workflow (always run, even during creation).
        # Skipped when entering Återsänd: the injected user_id=False would
        # otherwise bounce the stage back to "Väntar på handläggning".
        if "user_id" in vals and not entering_atersand:
            workflow_updates = stage_manager.handle_resource_assignment(
                self, vals.get("user_id")
            )
            vals.update(workflow_updates)

        # Custom loan product tracking
        loan_product_messages = (
            {} if skip_tracking else self._track_loan_product_changes(vals)
        )

        # MIM-1846: stamp the change time so every viewer of the request
        # gets an unacknowledged-change chip on the kanban card. Capture old
        # values before super().write() applies the new one.
        master_key_changed_ids = []
        if "master_key" in vals:
            new_master_key = vals["master_key"]
            for record in self:
                if record.master_key != new_master_key:
                    master_key_changed_ids.append(record.id)

        # Only track changes if not in creation phase
        change_tracker = FieldChangeTracker(self.env)
        changes_by_record = (
            {} if skip_tracking else change_tracker.track_field_changes(self, vals)
        )

        # Strip transient option fields from vals to prevent Odoo 19
        # web_read from caching and resolving deleted option records
        _option_fields = {
            "property_option_id",
            "building_option_id",
            "rental_property_option_id",
            "maintenance_unit_option_id",
            "tenant_option_id",
            "lease_option_id",
            "parking_space_option_id",
            "facility_option_id",
            "staircase_option_id",
        }
        for f in _option_fields:
            vals.pop(f, None)

        # Note: activity_update() is overridden to suppress automatic activities
        result = super().write(vals)

        if master_key_changed_ids:
            self.browse(master_key_changed_ids).write(
                {"master_key_changed_at": fields.Datetime.now()}
            )

        # Post loan product messages first, then other change notifications
        if not skip_tracking:
            self._post_loan_product_messages(loan_product_messages)
            change_tracker.post_change_notifications(self, changes_by_record)

        # MIM-486: hand returned requests back to the orderer's team. Resolved
        # here, after super().write(), so a write that changes owner_user_id
        # and the stage together uses the new orderer. sudo() keeps env.uid
        # (chatter author stays the returning user) but bypasses the
        # contractor record rule, which would otherwise reject the
        # contractor's own write once the team no longer includes them. Must
        # run last: after this the contractor may not see the record at all.
        if entering_atersand:
            team_to_record_ids = {}
            for record in self:
                team = stage_manager.resolve_return_team(record)
                if team and record.maintenance_team_id != team:
                    team_to_record_ids.setdefault(team.id, []).append(record.id)
            for team_id, record_ids in team_to_record_ids.items():
                self.browse(record_ids).sudo().write({"maintenance_team_id": team_id})

        return result

    def _track_loan_product_changes(self, vals):
        """Track loan product changes for existing records."""
        loan_product_messages = {}

        if "has_loan_product" not in vals and "loan_product_details" not in vals:
            return loan_product_messages

        for record in self:
            # Current state (before this write)
            old_has_loan = record.has_loan_product
            old_details = record.loan_product_details or ""

            # New state (after this write)
            new_has_loan = vals.get("has_loan_product", old_has_loan)
            new_details = vals.get("loan_product_details", old_details) or ""

            message = None

            # Loan product being returned (toggle OFF)
            if not new_has_loan and old_has_loan:
                message = (
                    f"Låneprodukt återlämnad: {old_details}"
                    if old_details
                    else "Låneprodukt återlämnad"
                )

            # Loan product being issued (toggle ON with details)
            elif new_has_loan and not old_has_loan and new_details:
                message = f"Låneprodukt utlämnad: {new_details}"

            # Details added to already-active loan product
            elif new_has_loan and old_has_loan and not old_details and new_details:
                message = f"Låneprodukt utlämnad: {new_details}"

            # Details updated while loan product is active
            elif (
                new_has_loan
                and old_has_loan
                and old_details
                and new_details != old_details
            ):
                message = f"Låneprodukt uppdaterad: {new_details}"

            if message:
                loan_product_messages[record.id] = message

        return loan_product_messages

    def _post_loan_product_messages(self, loan_product_messages):
        """Post loan product change messages to records."""
        for record in self:
            if record.id in loan_product_messages:
                html_content = (
                    f"<div><strong>{loan_product_messages[record.id]}</strong></div>"
                )
                record.message_post(
                    body=Markup(html_content),
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                )

    # ============================================================================
    # INTEGRATION METHODS
    # ============================================================================

    def open_time_report(self):
        self.ensure_one()
        # Property code of the request's location, whatever the space type
        estate_code = ManagementAreaService.get_property_code(self)

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

    def activity_update(self):
        """Override to completely suppress automatic maintenance activity creation.

        This prevents the creation of the specific 'Maintenance Request' activity
        that would normally be created when schedule_date is set. This activity
        is of type 'maintenance.mail_act_maintenance_request'.

        The suppression happens regardless of what triggers the activity_update()
        call (schedule_date, user_id, stage_id, etc.).

        Manual activities can still be created normally through the UI or API.
        """
        # Complete suppression of automatic maintenance activities
        # Simply return without calling super() to skip all activity operations
        return

    def open_customer_card(self):
        self.ensure_one()
        if not self.contact_code:
            return

        base_url = self.env["ir.config_parameter"].get_param(
            "onecore_frontend_url",
            "https://onecore.mimer.nu",
        )

        url = f"{base_url}/hyresgaster/{self.contact_code}"

        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }

    def call_phone_number(self):
        self.ensure_one()
        if not self.phone_number:
            return

        phone = self.phone_number.replace(" ", "").replace("-", "")

        self.message_post(
            body=f"Ringde hyresgästen på {self.phone_number}",
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )

        return {
            "type": "ir.actions.act_url",
            "url": f"tel:{phone}",
            "target": "self",
        }

    def open_google_maps(self):
        self.ensure_one()
        if not self.address:
            return

        formatted_address = urllib.parse.quote(self.address)
        url = f"https://maps.google.com/?q={formatted_address}"

        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }

    def open_component_wizard(self):
        self.ensure_one()
        # Create wizard explicitly so it has a real ID before loading components
        wizard = (
            self.env["maintenance.component.wizard"]
            .with_context(default_maintenance_request_id=self.id)
            .create(
                {
                    "maintenance_request_id": self.id,
                }
            )
        )
        return {
            "name": "Uppdatera/lägg till Komponent",
            "type": "ir.actions.act_window",
            "res_model": "maintenance.component.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "view_type": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {"dialog_size": "extra-large"},
        }

    # ============================================================================
    # DISTRIKT / RESURSGRUPP
    # ============================================================================

    def action_assign_district_team(self):
        """ "Tilldela resursgrupp": set the team paired with the request's
        district (OneCore cost center), fetching the district first when the
        request doesn't carry one yet (legacy requests)."""
        self.ensure_one()
        if ExternalContractorService(self.env).is_external_contractor():
            # The view hides the button; this guards RPC callers.
            raise UserError(
                "Endast interna användare kan tilldela resursgrupp utifrån distrikt."
            )
        result = ManagementAreaService(self.env).assign_team(self)
        if result["error"]:
            return self._district_team_notification(result["error"], "warning")
        team_name = result["team"].name
        if not result["changed"]:
            return self._district_team_notification(
                f"Ärendet ligger redan på {team_name}.", "info"
            )
        return self._district_team_notification(
            f"Resursgrupp satt till {team_name}.", "success"
        )

    @staticmethod
    def _district_team_notification(message, notification_type):
        # "next" is what makes the form show the new values without a manual
        # reload: a button that returns nothing gets act_window_close from the
        # web client, which triggers the record reload; a client action does
        # not. display_notification returns params.next, and the action service
        # runs it with the same onClose. Same pattern as hr_recruitment,
        # l10n_in and mail in stock Odoo. Needed for every outcome — the
        # warning case may have just fetched the district.
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Tilldela resursgrupp",
                "message": message,
                "type": notification_type,
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    @api.model
    def _cron_sync_kvv_areas(self):
        """Scheduled action (nightly): refresh the kvartersvärds- and
        distriktschefsmasters so both follow OneCore without any HTTP on the
        read path. One call for all 33 areas plus one tree per district."""
        service = ManagementAreaService(self.env)
        return service.sync_kvv_areas() + service.sync_cost_centers()

    @api.model
    def _cron_backfill_management_area(self, limit=5000):
        """Scheduled action (hourly): snapshot distrikt/kvartersvärdsområde on
        requests that lack one (created before the feature or while OneCore
        was down). Display only — never changes Resursgrupp/Resurs.

        The batch is large because the cost is the cost-center trees, fetched
        once per run, not per request."""
        return ManagementAreaService(self.env).backfill_batch(limit=limit)
