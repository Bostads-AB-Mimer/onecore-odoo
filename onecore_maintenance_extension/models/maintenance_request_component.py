from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .services import ComponentEventSyncService, ExternalContractorService

OUTCOMES = [
    ("REPAIRED", "Reparerad"),
    ("REPLACED", "Utbytt"),
    ("REMEDIED", "Åtgärdad"),
    ("RENEWED", "Förnyad"),
    ("NO_ACTION", "Ingen åtgärd"),
]
# The outcomes offered per category type, in button order. Surfaces are
# Åtgärdad (mended) or Förnyad (repainted, re-papered, relaid).
EQUIPMENT_OUTCOMES = ("REPAIRED", "REPLACED", "NO_ACTION")
SURFACE_OUTCOMES = ("REMEDIED", "RENEWED", "NO_ACTION")

# Where the outcome is in the sync to OneCore. Empty: nothing to send.
SYNC_STATES = [
    ("pending", "Väntar"),
    ("synced", "Synkad"),
    ("failed", "Misslyckad"),
    ("rejected", "Nekad"),
]
SYNC_CRON = "onecore_maintenance_extension.ir_cron_sync_component_events"
# Set by the server: write() drops a non-superuser's values, create()
# overwrites them after the rows exist
SERVER_SET_FIELDS = frozenset(
    {
        "outcome_user_id",
        "outcome_recorded_at",
        "sync_state",
        "sync_error",
        "core_event_id",
        "sync_attempted_at",
    }
)


class MaintenanceRequestComponent(models.Model):
    """A OneCore component that an ärende concerns, with a note.

    Space and name are snapshots taken when the component was selected, so
    the ärende still reads correctly when OneCore is down or the component
    is later renamed or uninstalled. The link itself lives only in Odoo.
    """

    _name = "maintenance.request.component"
    _description = "Komponent på ärende"
    _rec_name = "component_name"
    _order = "space_sequence, component_name, id"

    _component_uniq = models.Constraint(
        "unique (maintenance_request_id, onecore_component_id)",
        "Komponenten är redan vald på ärendet.",
    )

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Ärende", required=True, ondelete="cascade"
    )
    onecore_component_id = fields.Char("Komponent-id (OneCore)", required=True)
    installation_id = fields.Char("Installations-id (OneCore)")
    rental_id = fields.Char("Hyresobjekt (OneCore)")
    space_id = fields.Char("Utrymmes-id (OneCore)")
    space_name = fields.Char("Utrymme")
    # Position of the space in the grid, so the notes under the description
    # follow the same order without knowing the spaces.
    space_sequence = fields.Integer("Utrymmesordning")
    component_name = fields.Char("Komponent", required=True)
    # Shown under the name; tells two of the same type apart
    subtype_name = fields.Char("Undertyp")
    subtype_xpand_code = fields.Char("Undertyp, Xpand-kod")
    category_type = fields.Char("Kategorityp")
    note = fields.Text("Anteckning")

    # Registered with "Markera som utförd". outcome_user_id and
    # outcome_recorded_at are set by the server to whoever changes the
    # outcome or its note, and when.
    outcome = fields.Selection(OUTCOMES, string="Utfall")
    outcome_note = fields.Text("Vad som gjordes")
    outcome_user_id = fields.Many2one("res.users", string="Utfall registrerat av")
    outcome_recorded_at = fields.Datetime("Utfall registrerat", readonly=True)

    # The outcome as a component event in OneCore, sent by the sync cron
    sync_state = fields.Selection(
        SYNC_STATES, string="Synk till OneCore", index=True, readonly=True, copy=False
    )
    sync_error = fields.Text("Synkfel", readonly=True, copy=False)
    core_event_id = fields.Char("Händelse-id (OneCore)", readonly=True, copy=False)
    sync_attempted_at = fields.Datetime("Senast skickad", readonly=True, copy=False)

    @api.constrains("outcome", "category_type")
    def _check_outcome_fits_category_type(self):
        for component in self:
            if component.outcome and component.outcome not in dict(
                component._outcome_options()
            ):
                raise ValidationError(
                    _("Utfallet går inte att välja för %s.", component._summary_name())
                )

    def _outcome_options(self):
        """[(key, label)] of the outcomes this component can get, in button
        order. A component without a category type counts as equipment."""
        self.ensure_one()
        keys = SURFACE_OUTCOMES if self.category_type == "SURFACE" else EQUIPMENT_OUTCOMES
        labels = dict(self._fields["outcome"]._description_selection(self.env))
        return [(key, labels[key]) for key in keys]

    def _summary_name(self):
        """Name, subtype and space, e.g. 'Spis – Elspis (Kök)'."""
        self.ensure_one()
        name = self.component_name
        if self.subtype_name:
            name = f"{name} – {self.subtype_name}"
        if self.space_name:
            name = f"{name} ({self.space_name})"
        return name

    # Contractors may not change components once the ärende is in Utförd,
    # Avslutad or Återsänd (restricted_external)
    def _check_contractor_may_change(self, requests):
        if self.env.su:
            return
        service = ExternalContractorService(self.env)
        if not service.is_external_contractor():
            return
        restricted_stages = service.restricted_stages()
        # sudo only to read the stage; the record rules still decide access
        for request in requests.sudo():
            if request.stage_id in restricted_stages:
                raise AccessError(
                    _(
                        "Entreprenörer kan inte ändra komponenter på ett ärende som är %s.",
                        request.stage_id.name,
                    )
                )

    def _stamp_outcome_user(self):
        """Set outcome_user_id and outcome_recorded_at to the current user and
        time on components with an outcome, and clear both on components
        without one."""
        with_outcome = self.filtered("outcome")
        to_clear = (self - with_outcome).filtered(
            lambda c: c.outcome_user_id or c.outcome_recorded_at
        )
        if with_outcome:
            super(MaintenanceRequestComponent, with_outcome).write(
                {
                    "outcome_user_id": self.env.uid,
                    "outcome_recorded_at": fields.Datetime.now(),
                }
            )
        if to_clear:
            super(MaintenanceRequestComponent, to_clear).write(
                {"outcome_user_id": False, "outcome_recorded_at": False}
            )

    def _queue_events(self, old_event_types=None, trigger=True):
        """Queue the components whose event type changed for the sync cron:
        pending when the new outcome is sent to OneCore, empty when it isn't,
        both without the last result. Triggers the cron once when any
        component is pending.

        :param old_event_types: {id: event type or None} from before the
            write; None (create) takes every component
        :param trigger: False leaves triggering the cron to the caller
        """
        pending_ids, cleared_ids = [], []
        for component in self:
            event_type = ComponentEventSyncService.event_type(component)
            if old_event_types is not None and event_type == old_event_types[component.id]:
                continue
            if event_type:
                pending_ids.append(component.id)
            elif (
                component.sync_state
                or component.sync_error
                or component.core_event_id
                or component.sync_attempted_at
            ):
                cleared_ids.append(component.id)
        no_result = {"sync_error": False, "core_event_id": False, "sync_attempted_at": False}
        if cleared_ids:
            super(MaintenanceRequestComponent, self.browse(cleared_ids)).write(
                {"sync_state": False, **no_result}
            )
        if pending_ids:
            super(MaintenanceRequestComponent, self.browse(pending_ids)).write(
                {"sync_state": "pending", **no_result}
            )
            if trigger:
                self._trigger_sync()

    def _queue_again(self):
        """Put the failed and rejected rows back in the queue without their
        last result, as when their outcome was saved, and trigger the sync
        cron when any row waits to be sent."""
        self.filtered(lambda c: c.sync_state in ("failed", "rejected"))._queue_events(
            trigger=False
        )
        if self.filtered(lambda c: c.sync_state == "pending"):
            self._trigger_sync()

    @api.model
    def _trigger_sync(self):
        """Run the sync cron once this transaction is committed."""
        cron = self.env.ref(SYNC_CRON, raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    @api.model
    def _cron_sync_component_events(self):
        """Scheduled action (every 15 minutes, and triggered by every queued
        outcome): send the queued outcomes to OneCore as component events."""
        return ComponentEventSyncService(self.env).sync_queued()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # After create: the ärende may come from a context default, not vals.
        # For the same reason the stamps and the queue overwrite the
        # server-set fields on the created rows, whatever vals said.
        self._check_contractor_may_change(records.maintenance_request_id)
        if not self.env.su:
            records._stamp_outcome_user()
        records._queue_events()
        return records

    def write(self, vals):
        requests = self.maintenance_request_id
        if vals.get("maintenance_request_id"):
            requests |= self.env["maintenance.request"].browse(
                vals["maintenance_request_id"]
            )
        self._check_contractor_may_change(requests)
        # outcome_user_id follows the work: set on the components whose
        # outcome or note changes, kept where both are written unchanged
        changed = self.browse()
        if not self.env.su:
            vals = self._without_server_set(vals)
            changed = self.filtered(lambda c: c._outcome_changes(vals))
        old_event_types = (
            {c.id: ComponentEventSyncService.event_type(c) for c in self}
            if "outcome" in vals
            else None
        )
        result = super().write(vals)
        changed._stamp_outcome_user()
        if old_event_types is not None:
            self._queue_events(old_event_types)
        return result

    @staticmethod
    def _without_server_set(vals):
        return {key: value for key, value in vals.items() if key not in SERVER_SET_FIELDS}

    def _outcome_changes(self, vals):
        """Whether vals change this component's outcome or its note."""
        self.ensure_one()
        return any(
            field in vals and (self[field] or False) != (vals[field] or False)
            for field in ("outcome", "outcome_note")
        )

    def unlink(self):
        self._check_contractor_may_change(self.maintenance_request_id)
        return super().unlink()
