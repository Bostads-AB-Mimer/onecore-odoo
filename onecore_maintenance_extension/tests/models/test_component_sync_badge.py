"""The badge "Komponent ej synkad": when an ärende's component outcomes count
as not synced to OneCore, and where the form and the cards show it."""

import re
from datetime import timedelta

from lxml import etree

from odoo import Command, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import file_open

from ...models.constants import COMPONENT_SYNC_GRACE
from ..utils.test_utils import create_internal_user
from .test_maintenance_request_component import _apartment_request, _link_vals
from .test_mark_done import MarkDoneCase

CARD_TEMPLATE = "onecore_maintenance_extension/static/src/views/maintenance_request_item.xml"
BADGE = "Komponent ej synkad"
# The badges' titles say where to find what to do next
NEXT_STEP = "vad du behöver göra"


def _age(env, rows, age):
    """Set the rows' last write `age` (a timedelta) back from now, as if
    nothing has touched them since."""
    env.flush_all()
    env.cr.execute(
        "UPDATE maintenance_request_component SET write_date = %s WHERE id IN %s",
        (fields.Datetime.now() - age, tuple(rows.ids)),
    )
    env.invalidate_all()


WITHIN_GRACE = COMPONENT_SYNC_GRACE - timedelta(minutes=1)
PAST_GRACE = COMPONENT_SYNC_GRACE + timedelta(minutes=1)


@tagged("onecore")
class TestComponentSyncPending(TransactionCase):
    def setUp(self):
        super().setUp()
        self.request = _apartment_request(self.env)

    def _row(self, sync_state, outcome="REPAIRED", request=None, sync_error=False, **kwargs):
        """A component row with this outcome, then this sync_state and
        sync_error written as the cron writes them (as superuser)."""
        request = request or self.request
        component_id = f"comp-{len(request.component_ids) + 1}"
        request.write(
            {
                "component_ids": [
                    Command.create(
                        _link_vals(component_id, component_id, outcome=outcome, **kwargs)
                    )
                ]
            }
        )
        row = request.component_ids.filtered(
            lambda c: c.onecore_component_id == component_id
        )
        row.write({"sync_state": sync_state, "sync_error": sync_error})
        return row

    def test_without_rows_there_is_no_badge(self):
        self.assertFalse(self.request.component_ids)
        self.assertFalse(self.request.component_sync_pending)

    def test_a_failed_row_shows_the_badge(self):
        self._row("failed")

        self.assertTrue(self.request.component_sync_pending)

    def test_a_rejected_row_shows_the_badge(self):
        self._row("rejected")

        self.assertTrue(self.request.component_sync_pending)

    def test_a_pending_row_shows_no_badge_within_the_grace_period(self):
        row = self._row("pending")
        self.assertFalse(self.request.component_sync_pending)

        _age(self.env, row, WITHIN_GRACE)

        self.assertFalse(self.request.component_sync_pending)

    def test_a_pending_row_shows_the_badge_after_the_grace_period(self):
        row = self._row("pending")

        _age(self.env, row, PAST_GRACE)

        self.assertTrue(self.request.component_sync_pending)

    def test_a_synced_row_shows_no_badge(self):
        row = self._row("synced")
        _age(self.env, row, PAST_GRACE)

        self.assertFalse(self.request.component_sync_pending)

    def test_a_row_with_nothing_to_send_shows_no_badge(self):
        rows = self._row(False, outcome="REPLACED") | self._row(False, outcome=None)
        _age(self.env, rows, PAST_GRACE)

        self.assertFalse(rows.filtered("sync_state"))
        self.assertFalse(self.request.component_sync_pending)

    def test_one_unsynced_row_among_others_shows_the_badge(self):
        rows = (
            self._row("synced")
            | self._row(False, outcome="REPLACED")
            | self._row("pending")
        )
        _age(self.env, rows.filtered(lambda r: r.sync_state != "pending"), PAST_GRACE)
        self.assertFalse(self.request.component_sync_pending)

        self._row("failed")

        self.assertTrue(self.request.component_sync_pending)

    def test_each_request_gets_its_own_badge_in_one_batch(self):
        other = _apartment_request(self.env)
        self._row("failed")
        self._row("synced", request=other)
        self.env.invalidate_all()

        requests = self.request | other

        self.assertEqual(
            [request.component_sync_pending for request in requests], [True, False]
        )

    def test_the_badge_follows_a_new_sync_state_in_the_same_transaction(self):
        row = self._row("synced")
        self.assertFalse(self.request.component_sync_pending)

        row.write({"sync_state": "failed"})

        self.assertTrue(self.request.component_sync_pending)

    def test_a_new_write_on_a_pending_row_restarts_the_grace_period(self):
        row = self._row("pending")
        _age(self.env, row, PAST_GRACE)
        self.assertTrue(self.request.component_sync_pending)

        row.write({"outcome_note": "Bytt termostat"})

        self.assertEqual(row.sync_state, "pending")
        self.assertFalse(self.request.component_sync_pending)

    # -- the lines under the badge ------------------------------------------
    def test_without_unsynced_rows_there_is_no_message(self):
        self._row("synced")
        self._row(False, outcome="REPLACED")
        self._row("pending")

        self.assertFalse(self.request.component_sync_message)

    def test_the_message_says_why_each_component_is_not_synced(self):
        work_order = f"od-{self.request.id}"
        failed_error = (
            f"{work_order}: OneCore svarade inte. Utfallet skickas igen automatiskt. "
            "Kontakta en administratör om märket ligger kvar."
        )
        rejected_error = (
            f"{work_order}: OneCore tog inte emot utfallet för Frys: Invalid UUID "
            "format. Kontakta en administratör."
        )
        self._row("failed", sync_error=failed_error, space_sequence=0)
        self._row("rejected", sync_error=rejected_error, space_sequence=1)
        waiting = self._row("pending", space_sequence=2, space_name="Hall")
        self._row("synced", space_sequence=3)
        _age(self.env, waiting, PAST_GRACE)

        self.assertEqual(
            self.request.component_sync_message.split("\n"),
            [
                failed_error,
                rejected_error,
                f"{work_order}: Utfallet för comp-3 (Hall) väntar på att skickas "
                "till OneCore. Utfallet skickas automatiskt. Kontakta en "
                "administratör om märket ligger kvar.",
            ],
        )

    def test_a_row_without_a_stored_error_still_says_what_to_do(self):
        self._row("rejected", space_sequence=0)
        self._row("failed", space_sequence=1)

        lines = self.request.component_sync_message.split("\n")

        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertTrue(line.startswith(f"od-{self.request.id}: "))
        self.assertIn("Kontakta en administratör.", lines[0])
        self.assertIn(
            "skickas igen automatiskt. Kontakta en administratör om märket "
            "ligger kvar.",
            lines[1],
        )

    def test_a_row_hidden_from_the_user_still_shows_the_badge(self):
        user = create_internal_user(self.env)
        failed = self._row("failed")
        self._row("synced")
        # Hides the failed row from everyone but the superuser
        self.env["ir.rule"].create(
            {
                "name": "Test: hide failed component rows",
                "model_id": self.env["ir.model"]._get_id(
                    "maintenance.request.component"
                ),
                "domain_force": "[('sync_state', '!=', 'failed')]",
            }
        )
        self.env.invalidate_all()
        request = self.request.with_user(user)

        # The form reads the rows as the user before the badge
        self.assertNotIn(failed.id, request.component_ids.ids)
        self.assertTrue(request.component_sync_pending)


@tagged("onecore")
class TestComponentSyncBadgeAfterMarkDone(MarkDoneCase):
    def test_marking_done_shows_no_badge_until_the_grace_period_has_passed(self):
        request = self._request(_link_vals(), _link_vals("comp-spis", "Spis"))

        self._register(request, self._answers(request, outcome="REPAIRED"))

        rows = request.component_ids
        self.assertEqual(set(rows.mapped("sync_state")), {"pending"})
        as_user = request.with_user(self.internal_user)
        self.assertFalse(as_user.component_sync_pending)

        _age(self.env, rows, PAST_GRACE)

        self.assertTrue(as_user.component_sync_pending)


@tagged("onecore")
class TestComponentSyncBadgeViews(TransactionCase):
    def _card_template(self):
        with file_open(CARD_TEMPLATE, "rb") as template:
            return template.read().decode()

    def _arch(self, xml_id, view_type):
        view = self.env.ref(xml_id)
        return etree.fromstring(
            self.env["maintenance.request"].get_view(view.id, view_type)["arch"]
        )

    def test_the_form_shows_the_badge_while_component_sync_pending(self):
        arch = etree.fromstring(
            self.env["maintenance.request"].get_view(view_type="form")["arch"]
        )

        badges = arch.xpath(f"//div[span[normalize-space()='{BADGE}']]")
        self.assertEqual(len(badges), 1)
        self.assertEqual(badges[0].get("invisible"), "not component_sync_pending")
        self.assertIn("mimer-badge", badges[0].get("class").split())
        self.assertIn(NEXT_STEP, badges[0].get("title"))
        self.assertEqual(
            len(arch.xpath("//field[@name='component_sync_pending']")), 1
        )

    def test_the_form_shows_why_under_the_badge(self):
        arch = etree.fromstring(
            self.env["maintenance.request"].get_view(view_type="form")["arch"]
        )

        [message] = arch.xpath("//field[@name='component_sync_message']")
        self.assertEqual(message.get("readonly"), "1")
        self.assertEqual(message.get("nolabel"), "1")
        self.assertEqual(
            message.getparent().get("invisible"), "not component_sync_pending"
        )
        badge = arch.xpath(f"//div[span[normalize-space()='{BADGE}']]")[0]
        self.assertIs(next(badge.itersiblings("div")), message.getparent())

    def test_the_card_shows_the_badge_while_component_sync_pending(self):
        template = etree.fromstring(self._card_template().encode())

        badges = template.xpath(
            "//div[@t-if='record.component_sync_pending.raw_value']/span"
        )
        self.assertEqual(len(badges), 1)
        self.assertEqual(badges[0].text.strip(), BADGE)
        self.assertIn("mimer-badge", badges[0].get("class").split())
        self.assertIn(NEXT_STEP, badges[0].get("title"))

    def test_the_kanban_and_phone_views_load_every_field_the_card_reads(self):
        # The card gets only the fields its view declares, plus id; a missing
        # one breaks the card
        read = set(re.findall(r"\brecord\.(\w+)\.", self._card_template())) - {"id"}
        self.assertIn("component_sync_pending", read)

        for xml_id, view_type in (
            ("maintenance.hr_equipment_request_view_kanban", "kanban"),
            ("onecore_maintenance_extension.hr_equipment_request_view_mobile", "mobile"),
        ):
            with self.subTest(view_type):
                loaded = set(self._arch(xml_id, view_type).xpath("//field/@name"))
                self.assertFalse(read - loaded)
