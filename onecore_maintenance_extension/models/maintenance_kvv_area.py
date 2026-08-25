from odoo import api, fields, models


class OnecoreMaintenanceKvvArea(models.Model):
    """Local master of OneCore's kvv areas (kvartersvärdsområden).

    Synced from GET /kvv-areas by the management-area cron (MIM-1967) so the
    request form can show "Nuvarande kvartersvärd" without HTTP on the read
    path (MIM-1869) and without snapshotting the steward on the request —
    vikarie/steward changes in OneCore show up on every request within one
    cron interval. Rows are only written by the sync (sudo); areas removed in
    OneCore are kept, since old requests still reference their code.
    """

    _name = "maintenance.kvv.area"
    _description = "Kvartersvärdsområde (OneCore)"
    _order = "code"

    # Reads and writes key on the code; two rows would split them silently
    # (e.g. a manual cron run overlapping the scheduled one). Declared as
    # models.Constraint: Odoo 19 dropped _sql_constraints and only logs a
    # warning for it, so that form never creates the index.
    _code_uniq = models.Constraint(
        "unique (code)",
        "Kvartersvärdsområdets kod måste vara unik.",
    )

    code = fields.Char("Kod", required=True, index=True)
    name = fields.Char("Namn")
    cost_center_code = fields.Char("Kostnadsställe (kod)")
    cost_center_name = fields.Char("Distrikt")
    responsible_name = fields.Char("Kvartersvärd")
    responsible_email = fields.Char("Kvartersvärd e-post")
    responsible_phone = fields.Char("Kvartersvärd telefon")
    # Distriktschef/biträdande deliberately not here: they are attributes of
    # the cost center, and OneCore will serve them from GET /cost-centers.
    # That card (under MIM-1968) adds its own master keyed on
    # cost_center_code, which the request already carries.
    # Keycloak sub — equals res.users.oauth_uid; kept for the coming
    # "mina områden"-filters (MIM-1969)
    responsible_keycloak_id = fields.Char("Kvartersvärd Keycloak-id")
    synced_at = fields.Datetime("Senast ändrad vid synk", readonly=True)

    @api.depends("code", "name")
    def _compute_display_name(self):
        for area in self:
            area.display_name = area.name or area.code
