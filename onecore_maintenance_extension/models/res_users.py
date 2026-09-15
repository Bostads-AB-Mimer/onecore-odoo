from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    # MIM-2011: the user's AD unit (Entra ID ``officeLocation``), written at
    # every SSO login by onecore_auth from the Keycloak userinfo claim, and by
    # the one-off seed import for the password users who never log in via
    # SSO. Stored raw, exactly as AD has it: normalisation happens at lookup
    # (maintenance_ad_unit.normalize_ad_unit) so both write paths yield the
    # same data. Deliberately not readonly — the import wizard hides readonly
    # fields, and the seed import is the only way the ~260 password users ever
    # get a value.
    ad_office_location = fields.Char(
        string="AD-enhet",
        copy=False,
        help=(
            "Enheten enligt AD (officeLocation). Skrivs automatiskt vid "
            "inloggning via Keycloak, eller via import. Styr vilken "
            "resursgrupp som blir Beställande resursgrupp på ärenden som "
            "användaren skapar, via mappningen under Ärendehantering → "
            "Konfiguration → AD-enheter."
        ),
    )
