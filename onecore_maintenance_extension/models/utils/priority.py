"""Prioritet arithmetic for maintenance requests (MIM-2038).

Kept pure and record-free so the model and the 19.0.1.0.12 migration share
one implementation of the rules rather than two that can drift.

The load-bearing convention: these helpers do arithmetic and nothing else.
A day count of 0 means Akut. It does NOT mean "no priority" — and it cannot
be made to, because odoo/orm/fields_numeric.py:32 coerces False to 0 on the
way into an int4 column, so there is no nullable integer in the ORM. Anything
that decides "is a priority set?" must look at the nullable priority_expanded
Selection, never at a day count.
"""

from ..constants import PRIORITY_CUSTOM

DAYS_PER_WEEK = 7

# Below this many days a value reads better as days than as weeks: "7 dagar"
# rather than "1 vecka", which is also how the presets are worded.
MIN_DAYS_FOR_WEEKS = 14


def priority_days_from(preset, weeks):
    """Number of days to förfallodatum.

    Always returns an int, because fields.Integer cannot hold NULL — see the
    module docstring. A return of 0 means Akut *only* when preset is truthy;
    callers that need "is a priority set at all" must ask priority_expanded.

    Args:
        preset: a value from constants.PRIORITY_PRESETS, or False.
        weeks: number of weeks, only meaningful when preset is PRIORITY_CUSTOM.
    """
    if not preset:
        return 0
    if preset == PRIORITY_CUSTOM:
        return DAYS_PER_WEEK * weeks if weeks else 0
    return int(preset)


def priority_label_for(days):
    """Swedish rendering of a day count. Always returns a string."""
    if days == 0:
        return "Akut"
    if days >= MIN_DAYS_FOR_WEEKS and days % DAYS_PER_WEEK == 0:
        return "%d veckor" % (days // DAYS_PER_WEEK)
    if days == 1:
        return "1 dag"
    return "%d dagar" % days
