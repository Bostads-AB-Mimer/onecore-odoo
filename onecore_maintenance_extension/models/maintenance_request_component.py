from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .services import ExternalContractorService

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

    # Registered with "Markera som utförd". outcome_user_id is set by the
    # server to whoever changes the outcome or its note.
    outcome = fields.Selection(OUTCOMES, string="Utfall")
    outcome_note = fields.Text("Vad som gjordes")
    outcome_user_id = fields.Many2one("res.users", string="Utfall registrerat av")

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
        """Set outcome_user_id to the current user on components with an
        outcome, and clear it on components without one."""
        with_outcome = self.filtered("outcome")
        to_set = with_outcome.filtered(lambda c: c.outcome_user_id != self.env.user)
        to_clear = (self - with_outcome).filtered("outcome_user_id")
        if to_set:
            super(MaintenanceRequestComponent, to_set).write(
                {"outcome_user_id": self.env.uid}
            )
        if to_clear:
            super(MaintenanceRequestComponent, to_clear).write({"outcome_user_id": False})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # After create: the ärende may come from a context default, not vals
        self._check_contractor_may_change(records.maintenance_request_id)
        if not self.env.su:
            records._stamp_outcome_user()
        return records

    def write(self, vals):
        requests = self.maintenance_request_id
        if vals.get("maintenance_request_id"):
            requests |= self.env["maintenance.request"].browse(
                vals["maintenance_request_id"]
            )
        self._check_contractor_may_change(requests)
        if self.env.su:
            return super().write(vals)
        # outcome_user_id follows the work: set on the components whose
        # outcome or note changes, kept where both are written unchanged
        vals = {key: value for key, value in vals.items() if key != "outcome_user_id"}
        changed = self.filtered(lambda c: c._outcome_changes(vals))
        result = super().write(vals)
        changed._stamp_outcome_user()
        return result

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
