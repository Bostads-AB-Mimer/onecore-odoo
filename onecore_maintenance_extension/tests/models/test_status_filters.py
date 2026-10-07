"""Tests for the status, date and customer-info filters in the request
search view.

Aktiva, Utförda and Avslutade must split the requests into three without
overlap, and every filter that reads as "open" shares Aktiva's definition
(is_active_status). The domains are read from the search view's arch, the way
the web client gets them, and combined the way it combines them: ORed within
a group, ANDed across groups. Run as an internal user: root is an external
contractor in tests.
"""
import re
from collections import Counter
from datetime import timedelta
from itertools import chain

from lxml import etree
from odoo import fields
from odoo.fields import Domain
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval

from ..utils.test_utils import create_internal_user, create_maintenance_request

# Every stage, and which status filter it belongs to.
STAGES = {
    "maintenance.stage_0": "status_active",  # Väntar på handläggning
    "maintenance.stage_1": "status_active",  # Resurs tilldelad
    "maintenance.stage_3": "status_active",  # Påbörjad
    "maintenance.stage_4": "status_active",  # Väntar på beställda varor
    "maintenance.stage_5": "performed",  # Utförd
    "maintenance.stage_6": "done",  # Avslutad
    "onecore_maintenance_extension.stage_atersand": "status_active",
}
STATUS_FILTERS = ("status_active", "performed", "done")
# Stages a request cannot enter without an assigned resource.
NEEDS_RESOURCE = {
    "maintenance.stage_1",
    "maintenance.stage_3",
    "maintenance.stage_4",
    "maintenance.stage_5",
}
# The client starts a new filter group at each of these (search_arch_parser.js:
# visitSeparator, visitField and visitGroup all push a group).
GROUP_BREAKS = {"separator", "field", "group"}
SEARCH_DEFAULT = re.compile(r"search_default_(\w+)")


@tagged("onecore")
class TestStatusFilters(TransactionCase):
    def setUp(self):
        super().setUp()
        self.user = create_internal_user(self.env)

        self.by_stage = {
            xml_id: self._request(xml_id)
            for xml_id in STAGES
            if xml_id != "maintenance.stage_6"
        }
        # Avslutad by way of Utförd, as in real life: performed_date is
        # stamped on the way and survives the closing.
        self.by_stage["maintenance.stage_6"] = self._request(
            "maintenance.stage_5", "maintenance.stage_6"
        )
        self.archived = self._request("maintenance.stage_0")
        self.archived.write({"archive": True})

        self.requests = self.archived.union(*self.by_stage.values())

        # Parsed once: every helper below reads from these.
        self.arch = etree.fromstring(
            self.env["maintenance.request"]
            .with_user(self.user)
            .get_view(view_type="search")["arch"]
        )
        self.filters = {node.get("name"): node for node in self.arch.iter("filter")}
        self.groups = self._filter_groups()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _request(self, *stage_xml_ids):
        """A request moved through ``stage_xml_ids``, in order."""
        created = create_maintenance_request(self.env(user=self.user))
        # Re-browsed: the recordset from create() carries creating_records.
        request = (
            self.env["maintenance.request"].with_user(self.user).browse(created.id)
        )
        for xml_id in stage_xml_ids:
            if xml_id in NEEDS_RESOURCE and not request.user_id:
                # Assigning moves the request to Resurs tilldelad.
                request.write({"user_id": self.user.id})
            stage = self.env.ref(xml_id)
            if request.stage_id != stage:
                request.write({"stage_id": stage.id})
        return request

    def _filter_groups(self):
        """Filter names per group, as the client builds them from the
        search view's top level, hidden filters included."""
        groups = [[]]
        for node in self.arch:
            if node.tag in GROUP_BREAKS:
                groups.append([])
            elif node.tag == "filter":
                groups[-1].append(node.get("name"))
        return [group for group in groups if group]

    def _domain(self, name):
        return safe_eval(self.filters[name].get("domain"))

    def _search(self, *names):
        """The requests of this test that all the named filters let through.
        ANDs every filter, so only for filters from different groups."""
        domain = [("id", "in", self.requests.ids)]
        for name in names:
            domain += self._domain(name)
        return self.env["maintenance.request"].with_user(self.user).search(domain)

    def _client_search(self, *names):
        """What the web client lists with these filters on: ORed within a
        group, ANDed across groups."""
        unknown = set(names) - set(chain.from_iterable(self.groups))
        self.assertFalse(unknown, "not filters in the search view")
        domain = Domain("id", "in", self.requests.ids)
        for group in self.groups:
            active = [name for name in group if name in names]
            if active:
                domain &= Domain.OR(Domain(self._domain(name)) for name in active)
        return self.env["maintenance.request"].with_user(self.user).search(domain)

    def _with_status(self, status):
        return self.env["maintenance.request"].union(
            *(self.by_stage[xml_id] for xml_id, s in STAGES.items() if s == status)
        )

    # ------------------------------------------------------------------
    # Aktiva / Utförda / Avslutade
    # ------------------------------------------------------------------
    def test_fixture_covers_every_stage(self):
        """A stage added later must be placed in STAGES, or the split below
        says nothing about it."""
        Stage = self.env["maintenance.stage"]
        self.assertEqual(
            Stage.search([]), Stage.union(*(self.env.ref(x) for x in STAGES))
        )
        for xml_id, request in self.by_stage.items():
            self.assertEqual(request.stage_id, self.env.ref(xml_id), xml_id)

    def test_status_filters_split_the_requests_into_three(self):
        """Every non-archived request in exactly one of the three, Väntar på
        handläggning and Återsänd counted as active."""
        for status in STATUS_FILTERS:
            with self.subTest(status=status):
                self.assertEqual(
                    self._search(status, "active"), self._with_status(status)
                )

        found = [self._search(status, "active") for status in STATUS_FILTERS]
        self.assertEqual(sum(len(requests) for requests in found), len(self.by_stage))
        self.assertEqual(self.requests - self.archived, found[0].union(*found[1:]))

    def test_status_filters_are_one_group_of_their_own(self):
        """ORed with each other, ANDed with everything else."""
        status_group = next(g for g in self.groups if "status_active" in g)

        self.assertEqual(status_group, list(STATUS_FILTERS))

    def test_archive_filter_still_applies_on_top(self):
        self.assertEqual(self._search("status_active", "inactive"), self.archived)

    def test_is_active_status(self):
        """Both polarities: favorites and drilldowns negate search fields."""
        Request = self.env["maintenance.request"].with_user(self.user)
        scope = [("id", "in", self.requests.ids)]
        active = self._with_status("status_active") | self.archived

        self.assertEqual(Request.search(scope + [("is_active_status", "=", True)]), active)
        for negation in (("is_active_status", "=", False), ("is_active_status", "!=", True)):
            with self.subTest(negation=negation):
                self.assertEqual(Request.search(scope + [negation]), self.requests - active)

    def test_open_filters_leave_performed_out(self):
        """Blockerat, Klart and Ej schemalagt read as "open" next to Aktiva,
        so they share its definition: a performed request is in none of them."""
        # No request in the fixture has a planned date.
        self.assertEqual(
            self._search("unscheduled", "active"), self._with_status("status_active")
        )
        for name, state in (("kanban_state_block", "blocked"), ("kanban_state_done", "done")):
            with self.subTest(filter=name):
                self.requests.write({"kanban_state": state})
                self.assertEqual(
                    self._search(name, "active"), self._with_status("status_active")
                )

    # ------------------------------------------------------------------
    # Where lists open with filters already on
    # ------------------------------------------------------------------
    def test_calendar_combines_with_every_status_filter(self):
        """Ärendekalendern opens with Aktiva + Utförda, the set stock's hidden
        "To Do" stood for. Adding Avslutade must add the closed requests: next
        to that hidden filter, which was ANDed with it, the list went empty."""
        action = self.env.ref("maintenance.hr_equipment_request_action_cal")
        defaults = set(SEARCH_DEFAULT.findall(action.context))
        open_requests = self._with_status("status_active") | self._with_status("performed")

        self.assertEqual(defaults, {"active", "status_active", "performed"})
        self.assertEqual(self._client_search(*defaults), open_requests)
        self.assertEqual(
            self._client_search(*defaults, "done"), self.requests - self.archived
        )

    def test_every_search_default_resolves(self):
        """search_default_<name> is silently ignored when the search view has
        no filter or field by that name, and the list opens unfiltered. Checks
        every request action and every link on the resource group card."""
        known = set(self.filters) | {node.get("name") for node in self.arch.iter("field")}
        sources = [
            (action.xml_id or str(action.id), action.context or "")
            for action in self.env["ir.actions.act_window"].search(
                [("res_model", "=", "maintenance.request")]
            )
        ]
        card = etree.fromstring(
            self.env["maintenance.team"]
            .with_user(self.user)
            .get_view(self.env.ref("maintenance.maintenance_team_kanban").id, "kanban")["arch"]
        )
        sources += [
            (f"team card: {' '.join(node.itertext()).strip() or node.tag}", node.get("context"))
            for node in card.iter()
            if node.get("context")
        ]

        for source, context in sources:
            with self.subTest(source=source):
                self.assertLessEqual(set(SEARCH_DEFAULT.findall(context)), known)

    def test_filter_names_are_unique(self):
        """Two filters with one name make search_default_<name> ambiguous;
        stock names both Avslutad and Klart "done"."""
        names = Counter(node.get("name") for node in self.arch.iter("filter"))

        self.assertEqual([name for name, n in names.items() if n > 1], [])
        self.assertEqual(self.filters["done"].get("string"), "Avslutade")
        self.assertIn("kanban_state_done", names)

    def test_labels(self):
        self.assertEqual(
            {name: self.filters[name].get("string") for name in STATUS_FILTERS},
            {"status_active": "Aktiva", "performed": "Utförda", "done": "Avslutade"},
        )
        # Not "Aktiva ärenden": the default facet lets Utförda and Avslutade
        # through, and Aktiva is the status filter.
        self.assertEqual(self.filters["active"].get("string"), "Alla ärenden")
        self.assertEqual(self.filters["inactive"].get("string"), "Arkiverade ärenden")

    # ------------------------------------------------------------------
    # Förfallna and the date filters
    # ------------------------------------------------------------------
    def test_overdue_is_past_due_and_still_active(self):
        # In the test user's timezone, the one 'today' in the domain uses.
        today = fields.Date.context_today(self.requests)
        for request in self.requests:
            request.due_date = today - timedelta(days=1)
        due_today = self.by_stage["maintenance.stage_0"]
        due_today.due_date = today
        due_tomorrow = self.by_stage["maintenance.stage_1"]
        due_tomorrow.due_date = today + timedelta(days=1)

        self.assertEqual(
            self._search("overdue", "active"),
            self._with_status("status_active") - due_today - due_tomorrow,
        )

    def test_overdue_skips_requests_without_due_date(self):
        for request in self.requests:
            request.due_date = False

        self.assertFalse(self._search("overdue"))

    def test_date_filters_are_on_stored_date_fields(self):
        """A date filter on a field that is not stored breaks the dropdown.
        No label of their own: the filter shows the field's label, the same
        as the form and the list column."""
        Request = self.env["maintenance.request"]
        for name, field, label in (
            ("filter_due_date", "due_date", "Förfallodatum"),
            ("filter_performed_date", "performed_date", "Utfört datum"),
        ):
            with self.subTest(filter=name):
                self.assertEqual(self.filters[name].get("date"), field)
                self.assertIsNone(self.filters[name].get("string"))
                self.assertEqual(Request._fields[field].string, label)
                self.assertTrue(Request._fields[field].store)
                self.assertIn(Request._fields[field].type, ("date", "datetime"))

    def test_planned_and_due_date_filters_offer_future_periods(self):
        """Odoo's default periods stop at the current month and year, which
        makes "förfaller i november" unselectable in October. end_year must
        reach next year too, or a month across new year gets this year."""
        for name in ("filter_due_date", "filter_schedule_date"):
            with self.subTest(filter=name):
                self.assertGreater(int(self.filters[name].get("end_month", 0)), 0)
                self.assertGreaterEqual(int(self.filters[name].get("end_year", 0)), 1)

    def test_performed_date_finds_closed_requests_too(self):
        """Utfört datum is what an avtalsägare filters on; a request that was
        performed and then closed must still be found by it."""
        now = fields.Datetime.now()
        performed_now = self.env["maintenance.request"].with_user(self.user).search(
            [
                ("id", "in", self.requests.ids),
                ("performed_date", ">=", now - timedelta(hours=1)),
                ("performed_date", "<=", now + timedelta(hours=1)),
            ]
        )

        self.assertEqual(
            performed_now,
            self.by_stage["maintenance.stage_5"] | self.by_stage["maintenance.stage_6"],
        )

    # ------------------------------------------------------------------
    # Ny kundinfo
    # ------------------------------------------------------------------
    def test_new_customer_info(self):
        now = fields.Datetime.now()
        unread = self.by_stage["maintenance.stage_0"]
        unread.last_customer_message_at = now
        new_tenant = self.by_stage["maintenance.stage_3"]
        new_tenant.recently_added_tenant = True
        acknowledged = self.by_stage["maintenance.stage_4"]
        acknowledged.write(
            {
                "last_customer_message_at": now - timedelta(hours=1),
                "customer_message_ack_at": now,
            }
        )
        # Utförd is not a done stage: the tenant can still be waiting.
        performed = self.by_stage["maintenance.stage_5"]
        performed.last_customer_message_at = now
        closed = self.by_stage["maintenance.stage_6"]
        closed.write({"last_customer_message_at": now, "recently_added_tenant": True})

        self.assertEqual(
            self._search("new_customer_info"), unread | new_tenant | performed
        )
