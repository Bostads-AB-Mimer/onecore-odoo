from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .services import ExternalContractorService


class MaintenanceRequestComponent(models.Model):
    """A OneCore component that an ärende concerns, with a note.

    Room and label are snapshots taken when the component was selected, so
    the ärende still reads correctly when OneCore is down or the component
    is later renamed or uninstalled. The link itself lives only in Odoo.
    """

    _name = "maintenance.request.component"
    _description = "Komponent på ärende"
    _rec_name = "label"
    _order = "room_sequence, label, id"

    _component_uniq = models.Constraint(
        "unique (request_id, onecore_component_id)",
        "Komponenten är redan vald på ärendet.",
    )

    request_id = fields.Many2one(
        "maintenance.request", string="Ärende", required=True, ondelete="cascade"
    )
    onecore_component_id = fields.Char("Komponent-id (OneCore)", required=True)
    installation_id = fields.Char("Installations-id (OneCore)")
    room_id = fields.Char("Rums-id (OneCore)")
    room_name = fields.Char("Rum")
    # Position of the room in the grid, so the notes under the description
    # follow the same order without knowing the rooms.
    room_sequence = fields.Integer("Rumsordning")
    label = fields.Char("Komponent", required=True)
    category_type = fields.Char("Kategorityp")
    note = fields.Text("Anteckning")

    # Contractors choose components on site, but like their other edits not
    # once the ärende is in Utförd, Avslutad or Återsänd (restricted_external).
    # Record rules only see the domain, not the stage, so this is checked here.
    def _check_contractor_may_change(self, requests):
        if self.env.su:
            return
        service = ExternalContractorService(self.env)
        if not service.is_external_contractor():
            return
        # sudo only to read the stage; the record rules still decide access
        for request in requests.sudo():
            if service.get_restricted_status(request):
                raise AccessError(
                    _(
                        "Entreprenörer kan inte ändra komponenter på ett ärende som är %s.",
                        request.stage_id.name,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        self._check_contractor_may_change(
            self.env["maintenance.request"].browse(
                [vals["request_id"] for vals in vals_list if vals.get("request_id")]
            )
        )
        return super().create(vals_list)

    def write(self, vals):
        requests = self.request_id
        if vals.get("request_id"):
            requests |= self.env["maintenance.request"].browse(vals["request_id"])
        self._check_contractor_may_change(requests)
        return super().write(vals)

    def unlink(self):
        self._check_contractor_may_change(self.request_id)
        return super().unlink()
