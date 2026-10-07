from collections import defaultdict

from odoo import fields, models
from odoo.fields import Domain

from .services.ordering_department_service import clean_department

# The numbers on the resource group card, by stage xml-id — stage names are
# translated and renameable. "new_info" is any open request with something
# new from or about the customer to acknowledge; it has no stages of its own.
#
# The team's own queue ("Att göra"): what sits with the team.
QUEUE_BUCKETS = {
    "waiting": ("maintenance.stage_0",),
    "active": ("maintenance.stage_1", "maintenance.stage_3", "maintenance.stage_4"),
    "performed": ("maintenance.stage_5",),
    # A returned request is handed back to the team that ordered it, so it is
    # the team's to handle again.
    "returned": ("onecore_maintenance_extension.stage_atersand",),
    "new_info": None,
}
# "Bevakning av beställningar": what the team's people ordered that sits with
# someone else. Active is everything not Utförd or Avslutad, so Väntar på
# handläggning counts (the order is still out, picked up or not), and so does
# Återsänd: a request returned to a third team, e.g. Kundcenter because the
# orderer is in no resource group, is still open with someone else.
ORDERED_BUCKETS = {
    "active": (
        "maintenance.stage_0",
        "maintenance.stage_1",
        "maintenance.stage_3",
        "maintenance.stage_4",
        "onecore_maintenance_extension.stage_atersand",
    ),
    "performed": ("maintenance.stage_5",),
    "new_info": None,
}
CARD_BLOCKS = {"queue": QUEUE_BUCKETS, "ordered": ORDERED_BUCKETS}
BUCKET_LABELS = {
    "waiting": "Väntar på handläggning",
    "active": "Aktiva",
    "performed": "Utförda",
    "returned": "Återsända",
    "new_info": "Ny kundinfo",
}


class MaintenanceTeam(models.Model):
    _inherit = 'maintenance.team'

    # Väntar på handläggning. Name kept from before the card had more numbers.
    first_column_request_count = fields.Integer(
        compute='_compute_queue_request_counts',
        string="First Column Requests"
    )
    active_request_count = fields.Integer(
        "Aktiva", compute="_compute_queue_request_counts"
    )
    performed_request_count = fields.Integer(
        "Utförda", compute="_compute_queue_request_counts"
    )
    returned_request_count = fields.Integer(
        "Återsända", compute="_compute_queue_request_counts"
    )
    new_info_request_count = fields.Integer(
        "Ny kundinfo", compute="_compute_queue_request_counts"
    )
    ordered_active_count = fields.Integer(
        "Beställda, aktiva", compute="_compute_ordered_request_counts"
    )
    ordered_performed_count = fields.Integer(
        "Beställda, utförda", compute="_compute_ordered_request_counts"
    )
    ordered_new_info_count = fields.Integer(
        "Beställda, ny kundinfo", compute="_compute_ordered_request_counts"
    )
    # OneCore cost center (= distrikt) this team is responsible for, e.g.
    # "61140" for Distrikt Väst. "Tilldela resursgrupp" on a request pairs
    # request.cost_center_code with this field — never with the (translatable,
    # renameable) team name. Seeded from data/maintenance.team.csv.
    cost_center_code = fields.Char(
        string="Kostnadsställe (distrikt)",
        index=True,
        help="Kod för kostnadsstället/distriktet i OneCore, t.ex. 61140 för "
        "Distrikt Väst. Används av knappen 'Tilldela resursgrupp' på ärenden. "
        "För de förvalda resursgrupperna underhålls kopplingen i "
        "data/maintenance.team.csv och skrivs om därifrån vid varje "
        "moduluppgradering — ändringar här överlever bara till nästa release.",
    )

    # ------------------------------------------------------------------
    # Who the team's people are
    # ------------------------------------------------------------------
    def _member_departments(self):
        """AD departments of the members, in the form stamped on requests.

        A resource group is a work queue and orders nothing itself; what it
        ordered is what its people's departments ordered. sudo: a contractor
        cannot read other users. Active members only (the relation hides
        archived users) — an ex-member's department did not order on the
        team's behalf.
        """
        return {
            clean_department(member.ad_office_location)
            for member in self.sudo().member_ids
        } - {False}

    # ------------------------------------------------------------------
    # Counting, shared by the card numbers and the lists they open
    # ------------------------------------------------------------------
    def _bucket_stage_ids(self, buckets):
        """{bucket: stage ids}. new_info counts in every open stage."""
        open_stage_ids = set(self.env["maintenance.stage"].search([("done", "=", False)]).ids)
        result = {}
        for bucket, xml_ids in buckets.items():
            if xml_ids is None:
                result[bucket] = open_stage_ids
                continue
            stages = [self.env.ref(xml_id, raise_if_not_found=False) for xml_id in xml_ids]
            result[bucket] = {stage.id for stage in stages if stage}
        return result

    def _bucket_domain(self, buckets, bucket):
        domain = Domain("stage_id", "in", sorted(self._bucket_stage_ids(buckets)[bucket]))
        if buckets[bucket] is None:
            domain &= Domain("customer_message_unread", "=", True) | Domain(
                "recently_added_tenant", "=", True
            )
        return domain

    def _card_bucket_domain(self, key):
        """The stage condition behind one card number, e.g. "ordered:active".

        The drilldown actions filter on it through the search-only
        card_bucket field, so the stages behind a number are defined once,
        here, for both the count and the list it opens.
        """
        block, _sep, bucket = (key or "").partition(":")
        buckets = CARD_BLOCKS.get(block, {})
        if bucket not in buckets:
            raise ValueError(f"Unknown card bucket: {key!r}")
        return self._bucket_domain(buckets, bucket)

    def _count_requests_by_bucket(self, domain, groupby, buckets):
        """Count active requests matching ``domain`` per bucket and group.

        One query whatever the number of groups. Returns
        {group key: {bucket: count}}, the key being a tuple of the
        ``groupby`` values (ids for relations). Not tied to teams: the same
        call keyed on cost_center_code or kvv_area_code gives the numbers
        for a district or a kvv area.
        """
        stage_ids = self._bucket_stage_ids(buckets)
        counts = defaultdict(lambda: dict.fromkeys(buckets, 0))
        rows = self.env["maintenance.request"]._read_group(
            Domain(domain) & Domain("archive", "=", False),
            [*groupby, "stage_id", "customer_message_unread", "recently_added_tenant"],
            ["__count"],
        )
        for *keys, stage, message_unread, new_tenant, count in rows:
            key = tuple(k.id if isinstance(k, models.BaseModel) else k for k in keys)
            for bucket, xml_ids in buckets.items():
                if stage.id not in stage_ids[bucket]:
                    continue
                if xml_ids is None and not (message_unread or new_tenant):
                    continue
                counts[key][bucket] += count
        return counts

    def _compute_queue_request_counts(self):
        counts = self._count_requests_by_bucket(
            [("maintenance_team_id", "in", self.ids)],
            ["maintenance_team_id"],
            QUEUE_BUCKETS,
        )
        for team in self:
            team_counts = counts[(team.id,)]
            team.first_column_request_count = team_counts["waiting"]
            team.active_request_count = team_counts["active"]
            team.performed_request_count = team_counts["performed"]
            team.returned_request_count = team_counts["returned"]
            team.new_info_request_count = team_counts["new_info"]

    def _compute_ordered_request_counts(self):
        departments = {team.id: team._member_departments() for team in self}
        counts = self._count_requests_by_bucket(
            [("ordering_department", "in", sorted(set().union(*departments.values())))],
            ["ordering_department", "maintenance_team_id"],
            ORDERED_BUCKETS,
        )
        for team in self:
            totals = dict.fromkeys(ORDERED_BUCKETS, 0)
            for (department, at_team_id), bucket_counts in counts.items():
                # Ordered by the team's people and sitting with someone else;
                # what sits with the team is already in its own queue.
                if department in departments[team.id] and at_team_id != team.id:
                    for bucket, count in bucket_counts.items():
                        totals[bucket] += count
            team.ordered_active_count = totals["active"]
            team.ordered_performed_count = totals["performed"]
            team.ordered_new_info_count = totals["new_info"]

    # ------------------------------------------------------------------
    # Card drilldown
    # ------------------------------------------------------------------
    # One ir.actions.act_window record per number (maintenance_team_view.xml),
    # each with its own path and a domain on active_id. The URL keeps both, so
    # the list survives a new tab, a shared link or browser Back; an action
    # built here as a dict would fall back to the stock action or to an
    # unfiltered list.
    def _open_requests(self, block, heading):
        self.ensure_one()
        bucket = self.env.context.get("request_bucket")
        if bucket not in CARD_BLOCKS[block]:
            raise ValueError(f"Unknown request bucket: {bucket!r}")
        action = self.env["ir.actions.act_window"]._for_xml_id(
            f"onecore_maintenance_extension.action_team_{block}_{bucket}"
        )
        label = BUCKET_LABELS[bucket]
        title = f"{self.name}: {heading}{label.lower() if heading else label}"
        # The web client shows display_name before name. Only the click gets
        # the team in the title; a restored URL shows the record's own name.
        action.update(name=title, display_name=title)
        return action

    def action_open_queue_requests(self):
        """The requests behind one "Att göra" number (context: request_bucket)."""
        return self._open_requests("queue", "")

    def action_open_ordered_requests(self):
        """The requests behind one "Bevakning" number (context: request_bucket)."""
        return self._open_requests("ordered", "Beställda, ")
