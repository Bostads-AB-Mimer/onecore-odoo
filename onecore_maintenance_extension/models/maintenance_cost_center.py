from odoo import api, fields, models


class OnecoreMaintenanceCostCenter(models.Model):
    """Local master of OneCore's cost centers (distrikt).

    Synced nightly from GET /cost-centers + /cost-centers/{id}/tree, which
    already carry lead/deputy as hydrated Keycloak users. Lets the request form
    show "Distriktschef" without HTTP on the read path (MIM-1869) and without
    snapshotting people on the request — a new chef shows up everywhere after
    one sync. Keyed on the cost center code, which the request already stores.
    """

    _name = "maintenance.cost.center"
    _description = "Kostnadsställe/distrikt (OneCore)"
    _order = "code"

    # models.Constraint, not _sql_constraints: Odoo 19 ignores the latter with
    # only a warning, so the unique index would never be created.
    _code_uniq = models.Constraint(
        "unique (code)",
        "Kostnadsställets kod måste vara unik.",
    )

    code = fields.Char("Kod", required=True, index=True)
    name = fields.Char("Namn")
    lead_name = fields.Char("Distriktschef")
    lead_email = fields.Char("Distriktschef e-post")
    lead_phone = fields.Char("Distriktschef telefon")
    deputy_name = fields.Char("Biträdande distriktschef")
    deputy_email = fields.Char("Biträdande e-post")
    deputy_phone = fields.Char("Biträdande telefon")
    synced_at = fields.Datetime("Senast ändrad vid synk", readonly=True)

    @api.depends("code", "name")
    def _compute_display_name(self):
        for record in self:
            if record.code and record.name:
                record.display_name = f"{record.code} - {record.name}"
            else:
                record.display_name = record.name or record.code
