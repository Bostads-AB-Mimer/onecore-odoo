from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .services import ExternalContractorService


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

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # After create: the ärende may come from a context default, not vals
        self._check_contractor_may_change(records.maintenance_request_id)
        return records

    def write(self, vals):
        requests = self.maintenance_request_id
        if vals.get("maintenance_request_id"):
            requests |= self.env["maintenance.request"].browse(
                vals["maintenance_request_id"]
            )
        self._check_contractor_may_change(requests)
        return super().write(vals)

    def unlink(self):
        self._check_contractor_may_change(self.maintenance_request_id)
        return super().unlink()
