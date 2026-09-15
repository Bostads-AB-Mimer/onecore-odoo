"""AD-enhet → resursgrupp (MIM-2011).

AD has exactly one unit per person (``officeLocation``), but the values are
not normalised: "Kundcenter" and "Kundcenterenheten" are the same unit,
"Besiktings-" is a typo of "Besiktnings-", and "HR- och social hållbarhets
avdelningen" has a stray space. A Char on the team would force one spelling
per team; this table lets several raw AD strings point at the same team, and
lets the business (not a release) decide the mapping.

The raw value is what the list shows — nobody can fix a typo they cannot see.
The normalised value is what lookups and the unique constraint use.
"""

import re

from odoo import api, fields, models

_WHITESPACE = re.compile(r"\s+")
# "hållbarhets avdelningen" → "hållbarhetsavdelningen". Only this suffix:
# it is the one variant seen in prod, and a broader rule ("collapse every
# space before a word") would merge units that genuinely differ.
_SPACE_BEFORE_AVDELNINGEN = re.compile(r"\s+(?=avdelningen\b)")


def normalize_ad_unit(value):
    """Canonical form of an AD unit name for lookup and uniqueness.

    Trim, lowercase, collapse internal whitespace, drop a space before
    "avdelningen". Returns "" for an empty value. Shared by the mapping model
    and OrderingTeamService so the two can never disagree.
    """
    if not value:
        return ""
    normalized = _WHITESPACE.sub(" ", str(value)).strip().lower()
    return _SPACE_BEFORE_AVDELNINGEN.sub("", normalized)


class OnecoreMaintenanceAdUnit(models.Model):
    _name = "maintenance.ad.unit"
    _description = "AD-enhet → resursgrupp"
    _order = "name"

    # models.Constraint, not _sql_constraints: Odoo 19 ignores the latter with
    # only a warning, so the unique index would never be created. The
    # constraint is on the normalised value on purpose: two rows that differ
    # only in case or spacing would be one unit twice, and whichever one
    # search() returned first would win silently.
    _name_normalized_uniq = models.Constraint(
        "unique (name_normalized)",
        "En annan stavning av samma AD-enhet finns redan i listan.",
    )

    name = fields.Char(
        "AD-enhet",
        required=True,
        help="Exakt som det står i AD (officeLocation), inklusive stavfel.",
    )
    # precompute so the value is part of the INSERT and the unique constraint
    # fires inside create(), not first at flush. Implicitly readonly (no
    # inverse), so nobody can bypass the normalisation by writing it directly.
    name_normalized = fields.Char(
        compute="_compute_name_normalized",
        store=True,
        precompute=True,
    )
    team_id = fields.Many2one(
        "maintenance.team",
        string="Resursgrupp",
        required=True,
        ondelete="restrict",
        help=(
            "Resursgruppen som blir Beställande resursgrupp för ärenden "
            "skapade av användare med den här AD-enheten. En arkiverad "
            "resursgrupp ignoreras tills den aktiveras, så mappningen kan "
            "läggas in i förväg."
        ),
    )

    @api.depends("name")
    def _compute_name_normalized(self):
        for record in self:
            record.name_normalized = (
                normalize_ad_unit(record.name) if record.name else False
            )
