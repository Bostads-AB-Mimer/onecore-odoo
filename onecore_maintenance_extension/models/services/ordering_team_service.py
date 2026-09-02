"""Beställande resursgrupp on maintenance requests (MIM-1970).

Who *ordered* the request, as opposed to who it currently sits with
(``maintenance_team_id``). Stamped at create and never recomputed on read:

* ``create_uid`` names a person, not a resource group, and a person can be a
  member of several teams — and can move between them.
* A report that derives the orderer at read time rewrites history: "ordered by
  the district in March" must not become a different answer in May because
  somebody changed department.
* Mina sidor-ärenden are created over XML-RPC with a technical integration
  user as ``create_uid``, so a derivation is meaningless for the largest
  inflow. Those are resolved from ``creation_origin`` to Kundcenter instead —
  never from the integration user's team membership.

Write path only: create() and the backfill cron. The read path stays free of
work (MIM-1869).
"""

import logging

from odoo import fields

_logger = logging.getLogger(__name__)

# MIM-1916: resolve teams by xml-id, never by their (translatable) name.
KUNDCENTER_TEAM_XML_ID = "onecore_maintenance_extension.7"

# Tenant reports from mimer.nu. Kundcenter owns that inflow.
MIMER_NU_ORIGIN = "mimer-nu"


class OrderingTeamService:
    """Resolve, stamp and backfill the ordering team of a request."""

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def resolve_orderer_team(self, orderer):
        """First team ``orderer`` is a member of, or an empty recordset.

        Shared with MaintenanceStageManager.resolve_return_team so that "the
        orderer's team" has exactly one definition.
        """
        if not orderer:
            return self.env["maintenance.team"]
        return (
            self.env["maintenance.team"]
            .sudo()
            .search([("member_ids", "in", [orderer.id])], limit=1)
        )

    def kundcenter_team(self):
        """The Kundcenter team, or an empty recordset when it is missing."""
        team = self.env.ref(KUNDCENTER_TEAM_XML_ID, raise_if_not_found=False)
        return team or self.env["maintenance.team"]

    def resolve_ordering_team(self, request):
        """The resource group that ordered ``request``."""
        if request.creation_origin == MIMER_NU_ORIGIN:
            # A tenant ordered this, not a resource group. create_uid is the
            # technical integration user, so its team membership says nothing:
            # deriving from it would let a single membership change silently
            # claim that some team ordered thousands of tenant reports.
            return self.kundcenter_team()
        orderer = request.owner_user_id or request.create_uid
        return self.resolve_orderer_team(orderer) or self.kundcenter_team()

    # ------------------------------------------------------------------
    # create()
    # ------------------------------------------------------------------
    def populate(self, request):
        """Stamp the ordering team on ``request``. Returns True when written.

        A request that already carries an ordering team is left alone, so a
        caller that stamped the field itself (core over XML-RPC, later
        MIM-1971) wins over the derivation — same contract as the district
        snapshot in ManagementAreaService.populate.
        """
        request.ensure_one()
        if request.ordering_team_id:
            # The caller stamped the team itself. Keep it, but make the
            # denormalised district code follow: a caller that passes only the
            # team would otherwise leave it NULL forever — the backfill's
            # "ordering_team_id = False" domain can never come back for it, and
            # the "Beställande distrikt" facet would silently miss the request.
            if not request.ordering_cost_center_code:
                code = request.ordering_team_id.cost_center_code
                if code:
                    request.sudo().write({"ordering_cost_center_code": code})
            return False
        team = self.resolve_ordering_team(request)
        if not team:
            return False
        # sudo: creators over RPC (mimer.nu) and contractors must not be
        # blocked by record rules when the stamp is written.
        request.sudo().write(self._stamp_vals(team))
        return True

    @staticmethod
    def _stamp_vals(team, backfilled_at=None):
        """Ordering fields for ``team``. Nothing else is ever written."""
        vals = {
            "ordering_team_id": team.id,
            # Denormalised so the district facet does not have to join.
            "ordering_cost_center_code": team.cost_center_code or False,
        }
        if backfilled_at:
            vals["ordering_backfilled_at"] = backfilled_at
        return vals

    # ------------------------------------------------------------------
    # Backfill (cron) — ordering fields only, never team/resource/stage
    # ------------------------------------------------------------------
    def backfill_batch(self, limit=5000):
        """Stamp up to ``limit`` requests created before MIM-1970.

        The guess is derived from who created the request and which team they
        belong to *today* — the best that can be reconstructed after the fact.
        ``ordering_backfilled_at`` marks it as exactly that, so guessed rows
        stay distinguishable from the ones stamped at create.

        Pure DB work, no HTTP, hence the large batch. The domain is
        self-consuming: a stamped request drops out of the next run, so once
        the backlog is done this is one query that returns nothing.
        """
        Request = self.env["maintenance.request"].sudo()
        records = Request.search(
            [("ordering_team_id", "=", False)], order="id desc", limit=limit
        )
        if not records:
            return 0

        kundcenter = self.kundcenter_team()
        if not kundcenter:
            # Without the fallback nothing resolves and the very same rows
            # would come back every hour.
            _logger.warning(
                "Ordering-team backfill skipped: Kundcenter team (%s) not found",
                KUNDCENTER_TEAM_XML_ID,
            )
            return 0

        user_to_team = self._member_team_map()
        now = fields.Datetime.now()
        groups = {}  # team id -> request ids
        for record in records:
            if record.creation_origin == MIMER_NU_ORIGIN:
                team = kundcenter
            else:
                orderer = record.owner_user_id or record.create_uid
                team = (
                    user_to_team.get(orderer.id) if orderer else None
                ) or kundcenter
            groups.setdefault(team.id, []).append(record.id)

        Team = self.env["maintenance.team"].sudo()
        for team_id, ids in groups.items():
            Request.browse(ids).write(
                self._stamp_vals(Team.browse(team_id), backfilled_at=now)
            )

        _logger.info("Ordering-team backfill: %s requests stamped", len(records))
        return len(records)

    def _member_team_map(self):
        """user id -> first team, in the order search(limit=1) would pick it.

        One pass over a handful of teams instead of one search per request.
        ``search([])`` and ``search([...], limit=1)`` share the model's
        _order, so ``setdefault`` reproduces the single-record lookup exactly.
        """
        mapping = {}
        for team in self.env["maintenance.team"].sudo().search([]):
            for member in team.member_ids:
                mapping.setdefault(member.id, team)
        return mapping
