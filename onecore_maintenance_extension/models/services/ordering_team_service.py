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
        preferred = self._preferred_category_team(
            request.maintenance_request_category_id, orderer
        )
        if preferred:
            return preferred
        # No Kundcenter fallback here, deliberately. Kundcenter distributes
        # every request in the organisation, so their bucket is the largest one
        # by construction — quietly filing "we could not tell" in it would mix
        # 990 requests from 29 group-less creators (prod, 2026-09-03) in with
        # the ones they genuinely registered, and nobody could separate them
        # afterwards. An empty ordering team is the truthful answer: this
        # request has no known ordering unit. The AD/officeLocation work is
        # what will fill these in properly.
        return self.resolve_orderer_team(orderer)

    def _preferred_category_team(self, category, orderer):
        """Category-specific tie-break for someone in several teams.

        Anna Lundberg (Kundcenter) needs "Nyckelbeställningar" followed up
        apart from "Inkomna serviceanmälningar", but the same people are
        members of both — the ordinary "first team by id" rule always picks
        the older queue. Josefin Sjöberg: the key-order category is also used
        by kvartersvärdar, so this can never key off the category alone — it
        only fires when the orderer is actually a member of that category's
        preferred team, or a kvartersvärd's cylinderbyte would get credited
        to Kundcenter.
        """
        if not orderer or not category or not category.sudo().active:
            return self.env["maintenance.team"]
        team = category.sudo().preferred_ordering_team_id
        if not team:
            return self.env["maintenance.team"]
        # search(), not a plain field read: an archived preferred team must
        # never win, same as any other team (test_archived_team_is_never_the_orderer).
        return (
            self.env["maintenance.team"]
            .sudo()
            .search(
                [("id", "=", team.id), ("member_ids", "in", [orderer.id])], limit=1
            )
        )

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
            # No team to record, but stamp the timestamp anyway — same as
            # backfill_batch does for its own unresolvable rows. Without it
            # this request is indistinguishable from a true pre-MIM-1970
            # legacy row: the self-consuming backfill domain would revisit it
            # later and derive a team from the creator's *then-current*
            # membership, silently rewriting a history that was already
            # correctly "no team" at create time.
            request.sudo().write({"ordering_backfilled_at": fields.Datetime.now()})
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

        Pure DB work, no HTTP, hence the large batch. Requests whose orderer
        cannot be resolved (creator in no resource group) are stamped with the
        timestamp alone and keep an empty team — the truthful answer, and what
        keeps the domain self-consuming: without that stamp those ~990 rows
        would come back every single hour forever. Same pattern as
        ManagementAreaService.backfill_batch stamping unresolvable requests.
        """
        Request = self.env["maintenance.request"].sudo()
        records = Request.search(
            [
                ("ordering_team_id", "=", False),
                ("ordering_backfilled_at", "=", False),
            ],
            order="id desc",
            limit=limit,
        )
        if not records:
            return 0

        kundcenter = self.kundcenter_team()
        user_to_team = self._member_team_map()
        category_overrides = self._category_preferred_team_members()
        now = fields.Datetime.now()
        groups = {}  # team id (or False when unresolved) -> request ids
        for record in records:
            if record.creation_origin == MIMER_NU_ORIGIN:
                # Kundcenter distributes every request in the organisation, so
                # they are the right owner of the tenant inflow.
                team = kundcenter
            else:
                orderer = record.owner_user_id or record.create_uid
                team = None
                if orderer:
                    override = category_overrides.get(
                        record.maintenance_request_category_id.id
                    )
                    if override and orderer.id in override[1]:
                        team = override[0]
                    else:
                        team = user_to_team.get(orderer.id)
            groups.setdefault(team.id if team else False, []).append(record.id)

        Team = self.env["maintenance.team"].sudo()
        resolved = 0
        for team_id, ids in groups.items():
            if team_id:
                vals = self._stamp_vals(Team.browse(team_id), backfilled_at=now)
                resolved += len(ids)
            else:
                vals = {"ordering_backfilled_at": now}
            Request.browse(ids).write(vals)

        _logger.info(
            "Ordering-team backfill: %s requests processed, %s resolved",
            len(records),
            resolved,
        )
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

    def _category_preferred_team_members(self):
        """category id -> (preferred team, member id set), for categories
        that carry an override. Precomputed once per batch, same reasoning
        as ``_member_team_map``: a handful of categories, not one query per
        request.
        """
        mapping = {}
        Category = self.env["maintenance.request.category"].sudo()
        Team = self.env["maintenance.team"].sudo()
        for category in Category.search([("preferred_ordering_team_id", "!=", False)]):
            # search(), not a plain field read: a preferred team that has
            # since been archived must drop out here too, or the backfill
            # would stamp it while create() (via _preferred_category_team's
            # search) would not — exactly the divergence
            # test_archived_team_is_never_the_orderer exists to catch.
            team = Team.search([("id", "=", category.preferred_ordering_team_id.id)], limit=1)
            if not team:
                continue
            mapping[category.id] = (team, set(team.member_ids.ids))
        return mapping
