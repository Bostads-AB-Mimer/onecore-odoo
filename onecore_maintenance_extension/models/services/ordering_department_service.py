"""Beställande avdelning on maintenance requests (MIM-1970, MIM-2011).

Who *ordered* the request, as opposed to who it currently sits with
(``maintenance_team_id``). The orderer is a person, and every Mimer employee
belongs to exactly one unit in AD (Entra ID ``officeLocation``), so the
department is read straight off the orderer's user record — written there at
every SSO login by onecore_auth, or by the seed import for the password users.
No mapping table and no resource-group membership: a department is an
attribute of the person, not a work queue, and it is what the follow-up views
(MIM-1975/1976/1977) filter and group on. Resource groups stay what they are:
where a request sits, and where Återsänd hands it back to.

Stamped at create and never recomputed on read:

* A report that derives the orderer at read time rewrites history: "ordered by
  Distrikt Öst in March" must not become a different answer in May because
  somebody changed department.
* Mina sidor-ärenden are created over XML-RPC with a technical integration
  user as ``create_uid``, which has no department. Those are stamped with
  Kundcenter from ``creation_origin`` instead: Kundcenter receives,
  categorises and distributes the tenant inflow, so in business terms they
  are the orderer.

Write path only: create() and the backfill cron. The read path stays free of
work (MIM-1869).
"""

import logging

from odoo import fields

from ..constants import MIMER_NU_ORIGIN

_logger = logging.getLogger(__name__)

# ir.config_parameter key for the department stamped on Mina sidor requests.
# A parameter, not a constant: it has to match how AD spells the Kundcenter
# unit once the business has cleaned up the duplicates
# ("Kundcenter"/"Kundcenterenheten"), and following that must not take a
# release.
MIMER_NU_DEPARTMENT_PARAM = "onecore_maintenance_extension.mimer_nu_ordering_department"
MIMER_NU_DEPARTMENT_DEFAULT = "Kundcenter"


def clean_department(value):
    """The stored form of an AD unit: stripped, or False when empty.

    Shared by the create path and the backfill so the two can never
    disagree. Nothing beyond the strip: AD is being cleaned up to one
    spelling per unit, and the value is shown as-is in the search facet.
    """
    if not value:
        return False
    return str(value).strip() or False


class OrderingDepartmentService:
    """Resolve, stamp and backfill the ordering department of a request."""

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def mimer_nu_department(self):
        """The department stamped on tenant (Mina sidor) requests."""
        value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(MIMER_NU_DEPARTMENT_PARAM, MIMER_NU_DEPARTMENT_DEFAULT)
        )
        return clean_department(value)

    def department_of(self, user):
        """``user``'s AD unit, or False."""
        if not user:
            return False
        # sudo: the orderer may be read from a contractor's or the RPC
        # integration user's env, which has no business reading res.users.
        return clean_department(user.sudo().ad_office_location)

    def resolve_ordering_department(self, request):
        """The department that ordered ``request``, or False."""
        if request.creation_origin == MIMER_NU_ORIGIN:
            # A tenant ordered this. create_uid is the technical integration
            # user, whose own AD unit (if any) says nothing about who ordered.
            return self.mimer_nu_department()
        orderer = request.owner_user_id or request.create_uid
        return self.department_of(orderer)

    # ------------------------------------------------------------------
    # create()
    # ------------------------------------------------------------------
    def populate(self, request):
        """Stamp the ordering department on ``request``. Returns True when written.

        A request that already carries a department is left alone, so a
        caller that stamped the field itself (core over XML-RPC, later
        MIM-1971) wins over the derivation — same contract as the district
        snapshot in ManagementAreaService.populate.

        An orderer without an AD value leaves the field empty *and unstamped*.
        The value on the user arrives late by design — it is written at the
        person's first SSO login after the Keycloak mapper went live — and a
        department is a stable fact, not a membership that may since have
        changed. So the backfill is allowed to come back for the request once
        the value is there; it stamps ordering_backfilled_at itself when it
        gives up (backfill_batch).
        """
        request.ensure_one()
        if request.ordering_department:
            return False
        department = self.resolve_ordering_department(request)
        if not department:
            return False
        # sudo: creators over RPC (mimer.nu) and contractors must not be
        # blocked by record rules when the stamp is written.
        request.sudo().write({"ordering_department": department})
        return True

    # ------------------------------------------------------------------
    # Backfill (cron) — ordering fields only, never team/resource/stage
    # ------------------------------------------------------------------
    def backfill_batch(self, limit=5000):
        """Stamp up to ``limit`` requests that have no ordering department.

        Two populations share the domain: requests created before the field
        existed, and requests whose orderer had no AD value at create time.
        Both get the orderer's department *as it is today* — the best that can
        be reconstructed after the fact. ``ordering_backfilled_at`` marks it as
        exactly that, so guessed rows stay distinguishable from the ones
        stamped at create.

        Pure DB work, no HTTP, hence the large batch.

        The department reaches res.users only through the Keycloak login hook,
        at each person's next SSO login after the mapper went live (no seed
        import: password users are contractors, who never order). So an
        orderer without a value today is one of two things, and the two are
        treated differently:

        * an active user with an OAuth link — they simply have not logged in
          yet. The request is left alone, unstamped, and the next run tries
          again. Giving up here would strand every legacy request in the
          weeks after release, and reopening them afterwards is a manual SQL
          job nobody should have to remember.
        * anyone else — archived (left the company), or never linked to
          Keycloak (service accounts, contractors). A value will never come.
          The request is stamped with the timestamp alone and keeps an empty
          department: the truthful answer, and what keeps the domain
          self-consuming so those rows do not come back every hour forever.
          Same pattern as ManagementAreaService.backfill_batch stamping
          unresolvable requests.

        Pending rows still match the domain, so they occupy the batch window
        until their orderer logs in. That converges on its own; it is why the
        cron can ship inactive and be switched on as soon as the mapper is
        live, in any order.
        """
        Request = self.env["maintenance.request"].sudo()
        records = Request.search(
            [
                ("ordering_department", "=", False),
                ("ordering_backfilled_at", "=", False),
            ],
            order="id desc",
            limit=limit,
        )
        if not records:
            return 0

        mimer_nu = self.mimer_nu_department()
        user_departments, pending_user_ids = self._user_department_maps()
        now = fields.Datetime.now()
        groups = {}  # department (or False when given up) -> request ids
        pending = 0
        for record in records:
            if record.creation_origin == MIMER_NU_ORIGIN:
                department = mimer_nu
            else:
                orderer = record.owner_user_id or record.create_uid
                department = user_departments.get(orderer.id) if orderer else False
                if not department and orderer and orderer.id in pending_user_ids:
                    pending += 1
                    continue
            groups.setdefault(department or False, []).append(record.id)

        resolved = 0
        for department, ids in groups.items():
            vals = {"ordering_backfilled_at": now}
            if department:
                vals["ordering_department"] = department
                resolved += len(ids)
            Request.browse(ids).write(vals)

        _logger.info(
            "Ordering-department backfill: %s requests processed, %s resolved, "
            "%s left for a later run (orderer has not logged in yet)",
            len(records),
            resolved,
            pending,
        )
        return len(records)

    def _user_department_maps(self):
        """(user id -> department, ids of users whose value may still come).

        One query for the batch instead of one read per request.
        active_test=False: the creators of old requests may well have left
        the company since, and their department is still the truthful answer
        for what they ordered back then. Those archived users are never
        "pending", nor is anyone without an OAuth link — nothing will ever
        write a department for them.
        """
        rows = (
            self.env["res.users"]
            .sudo()
            .with_context(active_test=False)
            .search_read(
                [("share", "=", False)],
                ["ad_office_location", "active", "oauth_uid"],
            )
        )
        mapping = {}
        pending = set()
        for row in rows:
            department = clean_department(row["ad_office_location"])
            # A whitespace-only value is "no department", same as on the
            # create path.
            if department:
                mapping[row["id"]] = department
            elif row["active"] and row["oauth_uid"]:
                pending.add(row["id"])
        return mapping, pending
