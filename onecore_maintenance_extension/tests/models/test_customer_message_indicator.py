"""Tests for the "Meddelande från kund" signal (MIM-1960).

The tenant -> case channel is detected by message_type = 'from_tenant', the
value onecore's work-order service writes when it forwards a Mina-sidor
message. Acknowledgement is shared across BOTH audiences: the first person to
acknowledge it — a Mimer handler or an external contractor, whoever gets
there first — silences the status for everyone and is the only one whose
acknowledgement posts a receipt to the tenant.
"""

import importlib.util
import os

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.tools.sql import column_exists

from ..utils.test_utils import (
    create_internal_user,
    create_external_contractor_user,
    create_maintenance_request,
)
from ...models.constants import CUSTOMER_MESSAGE_TYPE, RECEIPT_TO_TENANT_MESSAGE_TYPE


def _get_or_create_mimer_user(env):
    """The integration account the work-order service posts as."""
    user = env["res.users"].sudo().search([("login", "=", "odoo@mimer.nu")], limit=1)
    if not user:
        user = (
            env["res.users"]
            .sudo()
            .create(
                {
                    "name": "Mimer Integration",
                    "login": "odoo@mimer.nu",
                    # message_post() writes a mail.message tied to the request,
                    # which needs write access on maintenance.request. Mirror
                    # the internal-handler groups so the team record rule lets
                    # the post through (base.group_user alone fails it).
                    "group_ids": [
                        (
                            6,
                            0,
                            [
                                env.ref("base.group_user").id,
                                env.ref("maintenance.group_equipment_manager").id,
                            ],
                        )
                    ],
                }
            )
        )
    return user


def _post_tenant_message(
    request, mimer_user, body="Hur går det?", message_type=CUSTOMER_MESSAGE_TYPE
):
    """Post exactly as odoo-adapter.addMessageToWorkOrder does: message_post
    with message_type='from_tenant' and the default note subtype."""
    return request.with_user(mimer_user).message_post(
        body=body, message_type=message_type
    )


def _load_ack_rename_migration():
    """Load migrations/19.0.1.0.6/pre-migration.py by path.

    The migration lives outside the importable package tree (the directory
    name is not a valid Python identifier), so it has to be loaded from its
    file location. Mirrors the idiom test_new_customer_info_indicator.py used
    for the 19.0.1.0.5 post-migration.
    """
    module_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    path = os.path.join(module_root, "migrations", "19.0.1.0.6", "pre-migration.py")
    spec = importlib.util.spec_from_file_location("mim_1960_pre_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CustomerMessageCase(TransactionCase):
    """Shared fixture: an internal user, a contractor on the request's team.

    The external-contractor record rule (security/maintenance.xml) only grants
    access to requests on the contractor's own team.
    """

    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        self.team = self.env["maintenance.team"].create({"name": "Test Team"})
        self.team.write({"member_ids": [(4, self.external_user.id)]})
        self.request = create_maintenance_request(
            self.env, maintenance_team_id=self.team.id
        )


@tagged("onecore")
class TestLastCustomerMessageAt(CustomerMessageCase):
    def test_from_tenant_message_sets_the_timestamp(self):
        message = _post_tenant_message(self.request, self.mimer_user)
        self.assertEqual(self.request.last_customer_message_at, message.date)

    def test_newer_message_moves_the_timestamp_forward(self):
        _post_tenant_message(self.request, self.mimer_user)
        second = _post_tenant_message(self.request, self.mimer_user, body="Igen")
        self.assertEqual(self.request.last_customer_message_at, second.date)

    def test_backdated_message_does_not_move_the_anchor_backwards(self):
        # The anchor must be the newest tenant message, so it may only ever
        # advance. A from_tenant message posted with an explicitly earlier
        # date (an import, a replay) must not move the anchor below the value
        # it already holds — that would silence a genuinely newer message.
        first = _post_tenant_message(self.request, self.mimer_user)
        earlier_date = first.date - timedelta(days=1)

        self.request.with_user(self.mimer_user).message_post(
            body="Efterhandsinlägg",
            message_type=CUSTOMER_MESSAGE_TYPE,
            date=earlier_date,
        )

        self.assertEqual(self.request.last_customer_message_at, first.date)

    def test_other_message_types_are_ignored(self):
        _post_tenant_message(self.request, self.mimer_user, message_type="comment")
        self.assertFalse(self.request.last_customer_message_at)

    def test_no_message_means_no_timestamp(self):
        self.assertFalse(self.request.last_customer_message_at)

    def test_the_write_logs_no_audit_note(self):
        # The request is written on every inbound tenant message. Without a
        # SKIP_FIELDS entry, FieldChangeTracker posts a chatter note about the
        # field change on top of the tenant's own message.
        #
        # create_maintenance_request()/create() leaves `creating_records=True`
        # on the returned recordset's context (see maintenance.py create()),
        # which makes write() skip FieldChangeTracker entirely. Tests that
        # assert on posted chatter notes must override it, same as
        # test_new_customer_info_indicator.py, test_master_key_change_indicator.py
        # and test_maintenance_workflow_service.py do.
        request = self.request.with_context(creating_records=False)
        before = set(request.message_ids.ids)
        _post_tenant_message(request, self.mimer_user)
        # message_ids is a plain relational field, not a compute — it was
        # already fetched (and cached) by the `before` read above, so it must
        # be explicitly invalidated to see the note just posted.
        request.invalidate_recordset(["message_ids"])
        new_bodies = " ".join(
            request.message_ids.filtered(lambda m: m.id not in before).mapped("body")
        )
        # Assert on the field LABEL: FieldChangeTracker logs labels, never
        # field names. Asserting on the name would pass even with the
        # SKIP_FIELDS entry removed.
        self.assertNotIn("Senaste meddelande från kund", new_bodies)


@tagged("onecore")
class TestAckColumn(CustomerMessageCase):
    """MIM-1844 gave "Ny kundinfo" two ack columns; its 1.0.6 migration
    renamed them onto the customer-message feature without changing the
    split. MIM-1960 goes further and collapses the pair into one shared
    column — this class now pins that collapse, not just the rename.
    """

    def test_shared_ack_field_exists(self):
        fields_ = self.env["maintenance.request"]._fields
        self.assertIn("customer_message_ack_at", fields_)

    def test_external_ack_field_is_gone(self):
        # MIM-1960: acknowledgement is shared, not per-audience, so the model
        # no longer needs a second column. The database column itself is
        # dropped by the follow-up migrations/19.0.1.0.7 task, not here — see
        # TestAckRenameMigration below for the transitional state where the
        # 19.0.1.0.6 migration still creates it as a raw, ORM-unmapped column.
        fields_ = self.env["maintenance.request"]._fields
        self.assertNotIn("customer_message_external_ack_at", fields_)

    def test_old_mim_1844_names_are_gone(self):
        fields_ = self.env["maintenance.request"]._fields
        self.assertNotIn("new_customer_info_ack_at", fields_)
        self.assertNotIn("new_customer_info_external_ack_at", fields_)

    def test_label_is_swedish_so_the_ack_reaches_the_audit_log(self):
        # FieldChangeTracker logs by field label; a missing/English label
        # would silently drop the acknowledgement from the chatter.
        fields_ = self.env["maintenance.request"]._fields
        self.assertIn("kund", fields_["customer_message_ack_at"].string.lower())


@tagged("onecore")
class TestAckRenameMigration(CustomerMessageCase):
    """Covers migrations/19.0.1.0.6/pre-migration.py directly (untouched by
    MIM-1960 — see "Do not touch" in the handoff doc). The suite installs
    modules fresh and never upgrades, so nothing else in the run exercises
    this script — see its own docstring for why it must be a pre-migration
    and why a rename resets both acks to NULL.

    The migration itself operates purely on raw column names via
    column_exists()/rename_column() — it has no dependency on the ORM field
    set, so it still runs exactly as before. Only the test SETUP changes:
    customer_message_external_ack_at is no longer an ORM field after
    MIM-1960, so the "old build" schema this test simulates has to create
    that column directly instead of renaming it away from a field that no
    longer exists.

    TransactionCase rolls back and Postgres DDL is transactional, so
    renaming maintenance_request's columns inside a test is safe; each test
    ends with the columns back the way the ORM expects them (either the
    migration renamed them back, or it never touched them).
    """

    def setUp(self):
        super().setUp()
        self.migration = _load_ack_rename_migration()

    def test_path_b_renames_and_resets_stale_narrow_acks(self):
        # Simulate a test/dev database still on the unreleased MIM-1844
        # build: the old columns exist, and one carries a non-NULL ack
        # written under the old narrow discriminator.
        cr = self.env.cr
        cr.execute(
            "ALTER TABLE maintenance_request "
            'RENAME COLUMN "customer_message_ack_at" TO "new_customer_info_ack_at"'
        )
        # customer_message_external_ack_at is not a field any more (MIM-1960),
        # so there is nothing to rename it from — add the old-named column
        # directly to reproduce the same raw-schema starting point.
        cr.execute(
            "ALTER TABLE maintenance_request ADD COLUMN "
            '"new_customer_info_external_ack_at" timestamp'
        )
        stale_ack = fields.Datetime.now()
        cr.execute(
            "UPDATE maintenance_request SET new_customer_info_ack_at = %s "
            "WHERE id = %s",
            (stale_ack, self.request.id),
        )
        self.env.invalidate_all()

        self.migration.migrate(cr, "19.0.1.0.5")
        self.env.invalidate_all()

        # column_exists(), not a hand-rolled information_schema query: the
        # same false-positive class (missing table_schema = current_schema)
        # that review had removed from the migration itself (MIM-1960 F3).
        self.assertTrue(
            column_exists(cr, "maintenance_request", "customer_message_ack_at")
        )
        # The rename migration still recreates this column raw — it is only
        # the ORM field that MIM-1960 removes. Dropping the column is the
        # follow-up migrations/19.0.1.0.7 task's job.
        self.assertTrue(
            column_exists(cr, "maintenance_request", "customer_message_external_ack_at")
        )
        self.assertFalse(
            column_exists(cr, "maintenance_request", "new_customer_info_ack_at")
        )
        self.assertFalse(
            column_exists(
                cr, "maintenance_request", "new_customer_info_external_ack_at"
            )
        )
        self.assertFalse(self.request.customer_message_ack_at)
        # Not an ORM field any more — read the raw column instead.
        cr.execute(
            "SELECT customer_message_external_ack_at FROM maintenance_request "
            "WHERE id = %s",
            (self.request.id,),
        )
        (external_ack,) = cr.fetchone()
        self.assertIsNone(external_ack)

    def test_path_a_is_a_no_op_on_the_natural_test_schema(self):
        # The test database's schema already matches post-upgrade production:
        # only the new columns exist. This is also the shape of a real
        # 1.0.4 -> 1.0.6 production upgrade at the point this script runs
        # (see its docstring) — neither old nor new columns exist there
        # either, so the loop finds nothing on both counts, but asserting
        # against a seeded ack on the natural test schema is the closest
        # this suite can get to that without fabricating a third schema
        # shape.
        #
        # Stored-field writes through the ORM only dirty the cache
        # (odoo/orm/fields.py ~1503-1521) — nothing flushes it to the
        # database on its own, and the request was created under
        # creating_records=True, which skips FieldChangeTracker but not the
        # underlying deferral. flush_all() is required *before* migrate() so
        # the column genuinely holds the seeded value while the migration
        # runs, mirroring what a real ack write followed by a real upgrade
        # looks like.
        seeded_ack = fields.Datetime.now()
        self.request.customer_message_ack_at = seeded_ack
        self.env.flush_all()

        self.migration.migrate(self.env.cr, "19.0.1.0.4")

        # Assert on the raw column, not through the ORM: env.invalidate_all()
        # defaults to flush=True (odoo/orm/environments.py ~357-366), which
        # would push the cached value back into the database *after*
        # migrate() ran and mask a real unconditional wipe. Reading straight
        # from Postgres is the only way this test can actually fail if the
        # reset guard regresses.
        self.env.cr.execute(
            "SELECT customer_message_ack_at FROM maintenance_request WHERE id = %s",
            (self.request.id,),
        )
        (stored_ack,) = self.env.cr.fetchone()
        self.assertEqual(stored_ack, seeded_ack)


def _load_old_ack_baseline_migration():
    """Load migrations/19.0.1.0.5/post-migration.py by path.

    Same idiom as _load_ack_rename_migration(): the directory name is not a
    valid Python identifier.
    """
    module_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    path = os.path.join(module_root, "migrations", "19.0.1.0.5", "post-migration.py")
    spec = importlib.util.spec_from_file_location("mim_1844_post_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("onecore")
class TestOldAckBaselineMigrationGuard(CustomerMessageCase):
    """Covers migrations/19.0.1.0.5/post-migration.py's column guard
    (untouched by MIM-1960 — see "Do not touch"). Unaffected by the
    shared-ack model change: the guard fires purely on
    column_exists(cr, TABLE, "new_customer_info_ack_at"), which is
    unconditionally False on every reachable schema (that column is never
    created under that name any more), so the guarded body — which the
    MIM-1960 model change does not touch — never runs either way.

    Odoo runs every version's pre-migration, then init_models(), then every
    version's post-migration in version order — so by the time this
    script's migrate() runs, init_models() has already applied the current
    field definitions, which only know the new column names. On every
    reachable database the old column is gone by then, so the guard must
    fire and the body must never execute (see the script's own docstring).
    """

    def setUp(self):
        super().setUp()
        self.migration = _load_old_ack_baseline_migration()

    def test_guard_is_a_no_op_on_the_natural_test_schema(self):
        # The test database's schema already matches every reachable
        # post-upgrade state: only the new columns exist. migrate() must
        # return immediately and leave a seeded ack untouched.
        #
        # Seed a real odoo@mimer.nu inbox notification so the migration's own
        # early returns (no integration user / no matching rows) cannot be
        # the reason nothing happens — production has 558 notification-
        # bearing requests, so this script's UPDATE is genuinely reached
        # there. Without the column guard, this would hit the UPDATE on the
        # renamed columns and raise a ProgrammingError.
        message = self.request.with_user(self.mimer_user).message_post(
            body="Ny info från hyresgäst",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        self.env["mail.notification"].sudo().create(
            {
                "mail_message_id": message.id,
                "res_partner_id": self.internal_user.partner_id.id,
                "notification_type": "inbox",
                "is_read": True,
            }
        )
        seeded_ack = fields.Datetime.now()
        self.request.customer_message_ack_at = seeded_ack
        self.env.flush_all()

        self.migration.migrate(self.env.cr, "19.0.1.0.5")

        # Assert on the raw column, not through the ORM: env.invalidate_all()
        # defaults to flush=True, which would push the cached value back into
        # the database *after* migrate() ran and mask a real unconditional
        # wipe (or a crash the ORM never surfaces). Reading straight from
        # Postgres is the only way this test can actually fail if the guard
        # regresses. Same trap documented on TestAckRenameMigration.
        self.env.cr.execute(
            "SELECT customer_message_ack_at FROM maintenance_request WHERE id = %s",
            (self.request.id,),
        )
        (stored_ack,) = self.env.cr.fetchone()
        self.assertEqual(stored_ack, seeded_ack)


@tagged("onecore")
class TestHasUnreadCustomerMessage(CustomerMessageCase):
    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_customer_message"])
        return record

    def test_from_tenant_message_raises_it_for_both_audiences(self):
        # "Statusen ska vara synlig för alla" — no group guard anywhere.
        _post_tenant_message(self.request, self.mimer_user)
        self.assertTrue(self._refresh(self.internal_user).has_unread_customer_message)
        self.assertTrue(self._refresh(self.external_user).has_unread_customer_message)

    def test_no_inbox_notification_needed(self):
        # The old MIM-1844 heuristic required one. The work-order service does
        # not create one, so requiring it missed real tenant messages.
        _post_tenant_message(self.request, self.mimer_user)
        self.env["mail.notification"].sudo().search(
            [
                ("mail_message_id.model", "=", "maintenance.request"),
                ("mail_message_id.res_id", "=", self.request.id),
            ]
        ).unlink()
        self.request.invalidate_recordset(["has_unread_customer_message"])
        self.assertTrue(self._refresh(self.internal_user).has_unread_customer_message)

    def test_comment_from_the_integration_user_does_not_raise_it(self):
        # The old heuristic matched any odoo@mimer.nu message with an inbox
        # notification, including plain comments.
        _post_tenant_message(self.request, self.mimer_user, message_type="comment")
        self.assertFalse(self._refresh(self.internal_user).has_unread_customer_message)

    def test_no_message_means_not_unread(self):
        self.assertFalse(self._refresh(self.internal_user).has_unread_customer_message)

    def test_reading_the_record_does_not_clear_it(self):
        _post_tenant_message(self.request, self.mimer_user)
        record = self._refresh(self.internal_user)
        _ = record.name  # simulate opening the form
        self.assertTrue(self._refresh(self.internal_user).has_unread_customer_message)


@tagged("onecore")
class TestAcknowledgeCustomerMessage(CustomerMessageCase):
    """MIM-1960: acknowledgement is one shared timestamp. The first person
    to acknowledge — from either audience — silences the status for
    everyone; a second acknowledger's call is a no-op."""

    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_customer_message"])
        return record

    def test_internal_ack_clears_it_for_everyone(self):
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()

        self.assertTrue(self.request.customer_message_ack_at)
        self.assertFalse(self._refresh(self.internal_user).has_unread_customer_message)
        self.assertFalse(self._refresh(self.external_user).has_unread_customer_message)

    def test_contractor_ack_clears_it_for_everyone(self):
        # The other order: a contractor acknowledging first must silence it
        # for Mimer too — the behaviour the owner explicitly asked for.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.external_user).action_acknowledge_customer_message()

        self.assertTrue(self.request.customer_message_ack_at)
        self.assertFalse(self._refresh(self.external_user).has_unread_customer_message)
        self.assertFalse(self._refresh(self.internal_user).has_unread_customer_message)

    def test_ack_is_shared_across_every_viewer(self):
        other_internal = create_internal_user(self.env)
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()
        self.assertFalse(self._refresh(other_internal).has_unread_customer_message)
        self.assertFalse(self._refresh(self.external_user).has_unread_customer_message)

    def test_second_acknowledger_does_not_move_the_timestamp(self):
        # The no-op guard (has_unread_customer_message already False) is what
        # stops a second acknowledger — this is the reported bug: previously
        # each audience had its own timestamp, so a second person from the
        # OTHER audience could still write one.
        #
        # fields.Datetime.now() truncates to whole seconds, so asserting
        # equality against "the first ack" is not reliable — an unguarded
        # second ack made within the same second would coincide with the
        # first and the assertion would still pass. Overwrite the ack with a
        # value the acknowledgement code could never produce on its own (ten
        # days in the future, which also keeps it past
        # last_customer_message_at so the guard still reads False), so only
        # the guard — not clock resolution — can keep the timestamp
        # byte-identical afterwards.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()

        distinctive_ack = fields.Datetime.now() + timedelta(days=10)
        self.request.sudo().write({"customer_message_ack_at": distinctive_ack})

        self.request.with_user(self.external_user).action_acknowledge_customer_message()

        self.assertEqual(self.request.customer_message_ack_at, distinctive_ack)

    def test_newer_message_re_raises_it_after_ack(self):
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()

        later = _post_tenant_message(self.request, self.mimer_user, body="Mer")
        later.date = self.request.customer_message_ack_at + timedelta(seconds=1)
        self.request.sudo().write({"last_customer_message_at": later.date})
        self.assertTrue(self._refresh(self.internal_user).has_unread_customer_message)

    def test_ack_with_nothing_unread_is_a_no_op(self):
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()
        self.assertFalse(self.request.customer_message_ack_at)

    def test_ack_is_written_to_the_audit_log(self):
        _post_tenant_message(self.request, self.mimer_user)
        # create_maintenance_request()/create() leaves `creating_records=True`
        # on the returned recordset's context (see maintenance.py create()),
        # which makes write() skip FieldChangeTracker entirely. Tests that
        # assert on posted chatter notes must override it, same as
        # test_new_customer_info_indicator.py and
        # test_master_key_change_indicator.py do.
        request = self.request.with_context(creating_records=False)
        before = set(request.message_ids.ids)
        request.with_user(self.internal_user).action_acknowledge_customer_message()
        # message_ids is a plain relational field, not a compute — it was
        # already fetched (and cached) by the `before` read above, so it must
        # be explicitly invalidated to see the note just posted.
        request.invalidate_recordset(["message_ids"])
        bodies = " ".join(
            request.message_ids.filtered(lambda m: m.id not in before).mapped("body")
        )
        self.assertIn("Meddelande från kund kvitterat", bodies)


@tagged("onecore")
class TestCustomerMessageOrdering(CustomerMessageCase):
    """ "Ärende med statusen 'meddelande från kund' ska sorteras högst upp i
    kanban vyn." _order can only read stored columns, hence the stored
    customer_message_unread boolean.
    """

    def _ordered_ids(self):
        return (
            self.env["maintenance.request"]
            .search([("id", "in", (self.request.id, self.other.id))])
            .ids
        )

    def setUp(self):
        super().setUp()
        self.other = create_maintenance_request(
            self.env, maintenance_team_id=self.team.id
        )
        # request_date is a Date defaulting to today
        # (odoo/addons/maintenance/models/maintenance.py:211), so two requests
        # made in one test share it and the _order tie-break is undefined.
        # Age self.request explicitly: plain date order then puts self.other
        # first, which is what makes the promotion assertions meaningful.
        today = fields.Date.context_today(self.request)
        self.other.request_date = today
        self.request.request_date = today - timedelta(days=1)

    def test_unread_customer_message_sorts_first(self):
        _post_tenant_message(self.request, self.mimer_user)
        self.assertEqual(self._ordered_ids()[0], self.request.id)

    def test_acknowledging_drops_it_back(self):
        # One shared ack is enough now — unlike the old per-audience split,
        # there is no "other side" left to also acknowledge.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()
        self.assertEqual(self._ordered_ids()[0], self.other.id)

    def test_contractor_acknowledging_also_drops_it_back(self):
        # Symmetry check: the promotion must clear regardless of which
        # audience acknowledges first.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.external_user).action_acknowledge_customer_message()
        self.assertEqual(self._ordered_ids()[0], self.other.id)

    def test_recently_added_tenant_still_sorts_below_customer_messages(self):
        self.other.recently_added_tenant = True
        _post_tenant_message(self.request, self.mimer_user)
        self.assertEqual(self._ordered_ids()[0], self.request.id)


@tagged("onecore")
class TestCustomerMessageReceipt(CustomerMessageCase):
    """ "Visa 'Mimer/leverantörens namn har mottagit ditt meddelande' för kunden
    i mina sidor och i händelseloggen i Odoo."

    Mina sidor renders any message_type other than 'from_tenant' as a message
    from Mimer, so the type only has to be allowlisted in the work-order
    service's MESSAGE_DOMAIN. It must never fire an SMS or an email.

    With a shared ack, reaching the write in action_acknowledge_customer_message
    always means the acking user is first — the receipt posts unconditionally
    there, and the pre-existing "if not has_unread_customer_message: return
    True" no-op guard is what stops a second acknowledger from posting again.
    """

    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_customer_message"])
        return record

    def _receipts(self):
        return self.request.message_ids.filtered(
            lambda m: m.message_type == RECEIPT_TO_TENANT_MESSAGE_TYPE
        )

    def test_internal_ack_posts_a_receipt_naming_mimer(self):
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()

        receipts = self._receipts()
        self.assertEqual(len(receipts), 1)
        self.assertIn("Mimer har mottagit ditt meddelande", receipts.body)

    def test_contractor_ack_posts_a_receipt_naming_the_team(self):
        # The ticket asks for the *supplier's* name, not the individual's.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.external_user).action_acknowledge_customer_message()

        receipts = self._receipts()
        self.assertEqual(len(receipts), 1)
        self.assertIn("Test Team har mottagit ditt meddelande", receipts.body)

    def test_second_ack_after_internal_posts_no_extra_receipt(self):
        # Mimer acks first -> posts, naming Mimer. The contractor's later
        # attempt on the SAME message is a no-op (has_unread_customer_message
        # is already False) and must not post a second receipt. This is
        # exactly the bug the owner reported: a second acknowledger from the
        # other audience used to be able to write its own timestamp and post
        # a duplicate receipt.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()
        self.request.with_user(self.external_user).action_acknowledge_customer_message()

        receipts = self._receipts()
        self.assertEqual(len(receipts), 1)
        self.assertIn("Mimer har mottagit ditt meddelande", receipts.body)

    def test_second_ack_after_contractor_posts_no_extra_receipt(self):
        # Mirror of the above: contractor acks first -> posts, naming the
        # team. Mimer's later attempt on the SAME message must not post a
        # second receipt.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.external_user).action_acknowledge_customer_message()
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()

        receipts = self._receipts()
        self.assertEqual(len(receipts), 1)
        self.assertIn("Test Team har mottagit ditt meddelande", receipts.body)

    def test_exactly_one_receipt_after_both_audiences_have_tried(self):
        # Explicit "exactly one receipt exists" coverage, independent of
        # which audience acted first — both orders funnel through the same
        # no-op guard.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.external_user).action_acknowledge_customer_message()
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()
        self.request.with_user(self.external_user).action_acknowledge_customer_message()

        self.assertEqual(len(self._receipts()), 1)

    def test_new_message_after_ack_re_raises_it_and_gets_its_own_receipt(self):
        # THE case a careless implementation breaks (already broken once on
        # this branch): once customer_message_ack_at is non-NULL, a guard
        # that only checks "is it NULL" would treat every later tenant
        # message as already acknowledged. The correct guard compares
        # last_customer_message_at against customer_message_ack_at, so a new
        # message re-raises the status for everyone, and the next
        # acknowledgement — here from the OTHER audience, to also prove the
        # re-raise is not scoped to whoever acked first — posts a fresh
        # receipt.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()
        self.assertEqual(len(self._receipts()), 1)

        # fields.Datetime truncates to whole seconds, so a message posted in
        # the same wall-clock second as the ack above would not compare as
        # newer (last_customer_message_at > ack_at would be False), and the
        # flag would not flip back to True. Force the new message strictly
        # past the ack, same as test_newer_message_re_raises_it_after_ack.
        later = _post_tenant_message(
            self.request, self.mimer_user, body="En till fråga"
        )
        later.date = self.request.customer_message_ack_at + timedelta(seconds=1)
        self.request.sudo().write({"last_customer_message_at": later.date})

        self.assertTrue(self._refresh(self.internal_user).has_unread_customer_message)
        self.assertTrue(self._refresh(self.external_user).has_unread_customer_message)

        self.request.with_user(self.external_user).action_acknowledge_customer_message()

        receipts = self._receipts().sorted("id")
        self.assertEqual(len(receipts), 2)
        self.assertIn("Mimer har mottagit ditt meddelande", receipts[0].body)
        self.assertIn("Test Team har mottagit ditt meddelande", receipts[-1].body)

    def test_ack_with_nothing_unread_posts_no_receipt(self):
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()
        self.assertFalse(self._receipts())

    def test_receipt_constant_is_not_an_outbound_tenant_dispatch_type(self):
        # Every tenant_* type sends a real SMS/email in mail.message.create.
        # Assert on the constant itself, not a hardcoded literal, so renaming
        # its value to a dangerous tenant_* form fails here by assertion,
        # rather than being caught only incidentally (e.g. by an unregistered
        # selection value raising elsewhere).
        self.assertFalse(RECEIPT_TO_TENANT_MESSAGE_TYPE.startswith("tenant_"))

    def test_ack_never_dispatches_a_real_sms_or_email(self):
        # The behavioural guard: whatever create()'s dispatch branch does in
        # the future, acknowledging a customer message must never reach the
        # real senders. Patches the senders on the class actually used by the
        # ORM (mail.message's registry class), following the
        # patch.object(type(...), ...) idiom used elsewhere in this suite
        # (see test_maintenance_component_line.py).
        _post_tenant_message(self.request, self.mimer_user)
        mail_message_cls = type(self.env["mail.message"])
        with patch.object(mail_message_cls, "_send_sms") as mock_send_sms:
            with patch.object(mail_message_cls, "_send_email") as mock_send_email:
                self.request.with_user(
                    self.internal_user
                ).action_acknowledge_customer_message()
        mock_send_sms.assert_not_called()
        mock_send_email.assert_not_called()

    def test_receipt_type_is_registered_on_mail_message(self):
        # Assert on the constant, not a bare literal, so it is genuinely the
        # value the module writes that is pinned to the registered selection
        # value — renaming the constant without updating the selection (or
        # vice versa) fails here.
        selection = dict(self.env["mail.message"]._fields["message_type"].selection)
        self.assertIn(RECEIPT_TO_TENANT_MESSAGE_TYPE, selection)

    def test_receipt_does_not_re_raise_the_customer_message_flag(self):
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.internal_user).action_acknowledge_customer_message()
        record = self.request.with_user(self.internal_user)
        record.invalidate_recordset(["has_unread_customer_message"])
        self.assertFalse(record.has_unread_customer_message)

    def test_contractor_receipt_does_not_trip_the_supplier_dialog_badge(self):
        # The receipt is a note authored by a contractor, and
        # _dialog_unread_message_ids looks at notes from the opposite party.
        # It is excluded because that pre-filter requires
        # message_type == "comment" AND informs_opposite_party, and the receipt
        # has neither. Pinned here so a future change to either cannot silently
        # start raising "Meddelande från leverantör" on every ack.
        _post_tenant_message(self.request, self.mimer_user)
        self.request.with_user(self.external_user).action_acknowledge_customer_message()

        record = self.request.with_user(self.internal_user)
        record.invalidate_recordset(["has_unread_supplier_dialog"])
        self.assertFalse(record.has_unread_supplier_dialog)


@tagged("onecore")
class TestCustomerMessageBadgeVisibility(CustomerMessageCase):
    """ "Statusen ska vara synlig för alla" — unlike the Ny kundinfo marker,
    this badge carries no group guard, and the field must load in every view
    whose template reads it."""

    def _kanban_arch(self, user):
        return (
            self.env["maintenance.request"]
            .with_user(user)
            .get_view(view_type="kanban")["arch"]
        )

    def test_field_loads_in_the_kanban_for_internal_users(self):
        self.assertIn(
            "has_unread_customer_message", self._kanban_arch(self.internal_user)
        )

    def test_field_loads_in_the_kanban_for_contractors(self):
        self.assertIn(
            "has_unread_customer_message", self._kanban_arch(self.external_user)
        )

    def test_field_loads_in_the_form_for_both_audiences(self):
        for user in (self.internal_user, self.external_user):
            arch = (
                self.env["maintenance.request"]
                .with_user(user)
                .get_view(view_type="form")["arch"]
            )
            self.assertIn("has_unread_customer_message", arch)


def _load_customer_message_migration():
    """Load migrations/19.0.1.0.6/post-migration.py by path.

    The migration sits outside the importable package tree — neither the
    directory nor the file name is a valid Python identifier.
    """
    module_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    path = os.path.join(module_root, "migrations", "19.0.1.0.6", "post-migration.py")
    spec = importlib.util.spec_from_file_location("mim_1960_post_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("onecore", "mim_1960")
class TestCustomerMessageAckBaseline(CustomerMessageCase):
    """MIM-1960 cutover (migrations/19.0.1.0.6/post-migration.py).

    MIM-1844 keyed on "authored by odoo@mimer.nu AND carrying an inbox
    notification" and baselined against that. The new rule is
    message_type='from_tenant', which matches a wider set — so without a
    re-baseline, historical tenant messages that never produced an inbox
    notification resurface as unread and get promoted to the top of the kanban.

    Was skipped: this script's raw SQL used to also write the now-removed
    customer_message_external_ack_at column and its SORT_FIELDS tuple used to
    look up the now-removed customer_message_unread_internal /
    customer_message_unread_external fields, both of which the MIM-1960 model
    change dropped in favour of one shared customer_message_ack_at /
    customer_message_unread. The follow-up migrations/19.0.1.0.7 task
    collapsed this script's writes onto the single column (see its own
    docstring), so it runs cleanly again against the current model — this
    class's assertions never referenced the removed columns in the first
    place, so re-enabling it required no assertion changes.
    """

    def setUp(self):
        super().setUp()
        self.migration = _load_customer_message_migration()

    def _notifications(self, request):
        return (
            self.env["mail.notification"]
            .sudo()
            .search(
                [
                    ("mail_message_id.model", "=", "maintenance.request"),
                    ("mail_message_id.res_id", "=", request.id),
                    ("notification_type", "=", "inbox"),
                ]
            )
        )

    def _reset_to_pre_migration_state(self, request):
        """Clear what the ORM already computed, leaving the state the migration
        actually meets: fresh NULL ack columns and no stored sort inputs."""
        request.sudo().write(
            {
                "customer_message_ack_at": False,
                "last_customer_message_at": False,
            }
        )

    def _baseline(self):
        return self.migration._baseline_customer_message_acks(self.env)

    def _unread_for(self, request, user):
        record = request.with_user(user)
        record.invalidate_recordset(["has_unread_customer_message"])
        return record.has_unread_customer_message

    def _create_inbox_notification(self, message, partner, is_read):
        """Seed a real inbox mail.notification row directly, the way
        MIM-1844's own fixtures did (test_new_customer_info_indicator.py).

        message_post()'s own recipient computation is not a reliable way to
        pin an exact read state here: the recipient's user notification
        preference decides email vs inbox (defaults to email, so a follower
        with no explicit preference gets an 'email' row, not 'inbox'), and a
        message with no follower at all produces no row whatsoever. Upserting
        the row directly sidesteps both and pins the exact pre-migration read
        state each test needs — updating in place when message_post() already
        created an (email-typed) row for this message/partner pair, since
        (mail_message_id, res_partner_id) is unique.
        """
        notification = (
            self.env["mail.notification"]
            .sudo()
            .search(
                [
                    ("mail_message_id", "=", message.id),
                    ("res_partner_id", "=", partner.id),
                ]
            )
        )
        if notification:
            notification.write({"notification_type": "inbox", "is_read": is_read})
            return notification
        return (
            self.env["mail.notification"]
            .sudo()
            .create(
                {
                    "mail_message_id": message.id,
                    "res_partner_id": partner.id,
                    "notification_type": "inbox",
                    "is_read": is_read,
                }
            )
        )

    def test_read_history_is_baselined_as_acknowledged(self):
        message = _post_tenant_message(self.request, self.mimer_user)
        self._create_inbox_notification(
            message, self.internal_user.partner_id, is_read=True
        )
        self._reset_to_pre_migration_state(self.request)

        updated, still_flagged = self._baseline()

        self.assertEqual(updated, 1)
        self.assertEqual(still_flagged, 0)
        self.assertEqual(self.request.customer_message_ack_at, message.date)
        self.assertFalse(self._unread_for(self.request, self.internal_user))
        self.assertFalse(self._unread_for(self.request, self.external_user))

    def test_outstanding_history_stays_flagged(self):
        message = _post_tenant_message(self.request, self.mimer_user)
        self._create_inbox_notification(
            message, self.internal_user.partner_id, is_read=False
        )
        self._reset_to_pre_migration_state(self.request)

        updated, still_flagged = self._baseline()

        self.assertEqual(updated, 1)
        self.assertEqual(still_flagged, 1)
        self.assertFalse(self.request.customer_message_ack_at)
        self.assertTrue(self._unread_for(self.request, self.internal_user))

    def test_message_with_no_inbox_notification_is_baselined_as_read(self):
        # THE regression this migration exists for. MIM-1844's aggregate joined
        # FROM mail_notification, so this request got no row and kept NULL acks.
        message = _post_tenant_message(self.request, self.mimer_user)
        self._notifications(self.request).unlink()
        self._reset_to_pre_migration_state(self.request)

        self._baseline()

        self.assertEqual(self.request.customer_message_ack_at, message.date)
        self.assertFalse(self._unread_for(self.request, self.internal_user))
        self.assertFalse(self._unread_for(self.request, self.external_user))

    def test_baseline_backfills_the_sort_input(self):
        message = _post_tenant_message(self.request, self.mimer_user)
        self._create_inbox_notification(
            message, self.internal_user.partner_id, is_read=True
        )
        self._reset_to_pre_migration_state(self.request)

        self._baseline()

        self.assertEqual(self.request.last_customer_message_at, message.date)
        # Acked, so it must not be promoted by _order.
        self.assertFalse(self.request.customer_message_unread)

    def test_request_without_tenant_messages_is_untouched(self):
        self._reset_to_pre_migration_state(self.request)
        updated, still_flagged = self._baseline()
        self.assertEqual(updated, 0)
        self.assertEqual(still_flagged, 0)
        self.assertFalse(self.request.last_customer_message_at)

    def test_rerun_does_not_clobber_a_post_upgrade_ack(self):
        message = _post_tenant_message(self.request, self.mimer_user)
        self._create_inbox_notification(
            message, self.internal_user.partner_id, is_read=True
        )
        self._reset_to_pre_migration_state(self.request)
        self._baseline()

        later = self.request.customer_message_ack_at + timedelta(days=1)
        self.request.sudo().write({"customer_message_ack_at": later})

        self._baseline()

        self.assertEqual(self.request.customer_message_ack_at, later)

    def test_contractor_read_state_does_not_decide_the_verdict(self):
        # Contractor inbox rows carry no signal about whether the tenant's
        # message is outstanding — the reason MIM-1844 documents.
        # Subscribe the contractor first: team membership alone does not make
        # them a follower — real production inbox notifications for a
        # contractor require it. Seeded directly (see
        # _create_inbox_notification) since message_post()'s own recipient
        # computation cannot be relied on here: the fallback subtype for an
        # un-typed post is mail.mt_note (default=False), so a plain
        # message_subscribe() never enrolls the follower for it.
        self.request.sudo().message_subscribe(
            partner_ids=self.external_user.partner_id.ids
        )
        message = _post_tenant_message(self.request, self.mimer_user)
        contractor_rows = self._create_inbox_notification(
            message, self.external_user.partner_id, is_read=False
        )
        self.assertTrue(
            contractor_rows,
            "no contractor inbox row — the test would not exercise the FILTER",
        )
        self._reset_to_pre_migration_state(self.request)

        _updated, still_flagged = self._baseline()

        self.assertEqual(still_flagged, 0)

    def test_baseline_uses_the_latest_message_and_any_unread_row(self):
        # Restores the multi-message coverage MIM-1844 had
        # (test_baseline_uses_the_latest_message) for the aggregate's MAX /
        # BOOL_OR interaction, lost when this branch replaced that migration.
        #
        # Two from_tenant messages: the OLDER one carries the unread inbox
        # notification, the NEWER one is already read. This pins two things
        # at once: the anchor must take MAX(date) over both messages (not the
        # first or the last posted), and "still flagged" must be driven by
        # whether ANY qualifying row is unread across the whole group — not
        # merely by the newest message's own read state, which here is read.
        older = _post_tenant_message(self.request, self.mimer_user, body="Först")
        older = older.sudo()
        older.write({"date": older.date - timedelta(days=2)})
        self._create_inbox_notification(
            older, self.internal_user.partner_id, is_read=False
        )

        newer = _post_tenant_message(self.request, self.mimer_user, body="Sedan")
        newer = newer.sudo()
        newer.write({"date": newer.date - timedelta(days=1)})
        self._create_inbox_notification(
            newer, self.internal_user.partner_id, is_read=True
        )
        self._reset_to_pre_migration_state(self.request)

        updated, still_flagged = self._baseline()

        self.assertEqual(updated, 1)
        self.assertEqual(still_flagged, 1)
        self.assertEqual(self.request.last_customer_message_at, newer.date)
        self.assertFalse(self.request.customer_message_ack_at)
        self.assertTrue(self._unread_for(self.request, self.internal_user))


def _load_ack_merge_migration():
    """Load migrations/19.0.1.0.7/pre-migration.py by path.

    Same idiom as _load_ack_rename_migration(): the directory name is not a
    valid Python identifier.
    """
    module_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    path = os.path.join(module_root, "migrations", "19.0.1.0.7", "pre-migration.py")
    spec = importlib.util.spec_from_file_location("mim_1960_ack_merge_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("onecore", "mim_1960")
class TestAckMergeMigration(CustomerMessageCase):
    """Covers migrations/19.0.1.0.7/pre-migration.py: merging
    customer_message_external_ack_at into customer_message_ack_at (the
    furthest-advanced non-null watermark wins — one audience's
    acknowledgement counts for both under the new shared semantics) and
    dropping that column plus the two orphaned sort booleans
    customer_message_unread_internal / customer_message_unread_external.

    Only a test/dev database still on 19.0.1.0.6 (state T in the handoff doc)
    carries the external column and the orphan columns; a real 1.0.4 -> 1.0.7
    production upgrade (state P) never creates them — see the migration's own
    docstring for why Odoo's migration ordering guarantees that. Both shapes
    are covered here.

    TransactionCase rolls back and Postgres DDL is transactional, so adding
    and dropping maintenance_request's columns inside a test is safe (same
    reasoning TestAckRenameMigration documents).
    """

    def setUp(self):
        super().setUp()
        self.migration = _load_ack_merge_migration()

    def _add_external_ack_column(self):
        """Simulate state T: a database still on 19.0.1.0.6, which has both
        ack columns."""
        self.env.cr.execute(
            "ALTER TABLE maintenance_request "
            'ADD COLUMN "customer_message_external_ack_at" timestamp'
        )

    def _add_orphan_sort_columns(self):
        self.env.cr.execute(
            "ALTER TABLE maintenance_request "
            'ADD COLUMN "customer_message_unread_internal" boolean'
        )
        self.env.cr.execute(
            "ALTER TABLE maintenance_request "
            'ADD COLUMN "customer_message_unread_external" boolean'
        )

    def _set_raw(self, request, column, value):
        self.env.cr.execute(
            f"UPDATE maintenance_request SET {column} = %s WHERE id = %s",
            (value, request.id),
        )

    def _raw_ack(self, request):
        # Not an ORM field read: the ORM cache could serve a stale value and
        # hide a real database change (the trap this suite documents
        # elsewhere — see TestAckRenameMigration).
        self.env.cr.execute(
            "SELECT customer_message_ack_at FROM maintenance_request WHERE id = %s",
            (request.id,),
        )
        (value,) = self.env.cr.fetchone()
        return value

    def test_merge_keeps_the_furthest_advanced_watermark(self):
        # All four NULL combinations of (customer_message_ack_at,
        # customer_message_external_ack_at) in one pass. earlier/later are
        # built two days apart so LEAST/GREATEST can never tie.
        self._add_external_ack_column()

        earlier = fields.Datetime.now() - timedelta(days=2)
        later = fields.Datetime.now() - timedelta(days=1)

        both_null = create_maintenance_request(self.env)
        ack_only = create_maintenance_request(self.env)
        ext_only = create_maintenance_request(self.env)
        ack_is_later = create_maintenance_request(self.env)
        ext_is_later = create_maintenance_request(self.env)

        self._set_raw(ack_only, "customer_message_ack_at", earlier)
        self._set_raw(ext_only, "customer_message_external_ack_at", earlier)
        self._set_raw(ack_is_later, "customer_message_ack_at", later)
        self._set_raw(ack_is_later, "customer_message_external_ack_at", earlier)
        self._set_raw(ext_is_later, "customer_message_ack_at", earlier)
        self._set_raw(ext_is_later, "customer_message_external_ack_at", later)
        self.env.flush_all()

        self.migration.migrate(self.env.cr, "19.0.1.0.6")

        self.assertIsNone(self._raw_ack(both_null))
        self.assertEqual(self._raw_ack(ack_only), earlier)
        self.assertEqual(self._raw_ack(ext_only), earlier)
        self.assertEqual(self._raw_ack(ack_is_later), later)
        self.assertEqual(self._raw_ack(ext_is_later), later)

    def test_merge_does_not_resurface_a_message_the_later_watermark_already_saw(self):
        # The bug this migration exists to fix: a contractor acknowledges at
        # t1, a tenant message arrives at t2, Mimer acknowledges at t3
        # (t1 < t2 < t3). The watermarks straddle the message — the earlier
        # one (contractor) predates it, the later one (Mimer) postdates it.
        # LEAST(t3, t1) = t1 would leave t2 > ack, resurfacing the row as
        # unread. GREATEST(t3, t1) = t3 correctly keeps it silent, because
        # Mimer's watermark already covers that message.
        self._add_external_ack_column()

        t1 = fields.Datetime.now() - timedelta(days=3)
        t2 = fields.Datetime.now() - timedelta(days=2)
        t3 = fields.Datetime.now() - timedelta(days=1)

        self._set_raw(self.request, "customer_message_external_ack_at", t1)
        self._set_raw(self.request, "customer_message_ack_at", t3)
        self._set_raw(self.request, "last_customer_message_at", t2)
        self.env.flush_all()
        self.env.invalidate_all()

        self.migration.migrate(self.env.cr, "19.0.1.0.6")

        self.assertEqual(self._raw_ack(self.request), t3)

        self.env.invalidate_all()
        model = self.env["maintenance.request"]
        records = model.browse(self.request.ids)
        self.env.add_to_compute(model._fields["customer_message_unread"], records)
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertFalse(self.request.customer_message_unread)

    def test_merge_drops_the_external_and_orphan_columns(self):
        self._add_external_ack_column()
        self._add_orphan_sort_columns()

        self.migration.migrate(self.env.cr, "19.0.1.0.6")

        self.assertFalse(
            column_exists(
                self.env.cr,
                "maintenance_request",
                "customer_message_external_ack_at",
            )
        )
        self.assertFalse(
            column_exists(
                self.env.cr,
                "maintenance_request",
                "customer_message_unread_internal",
            )
        )
        self.assertFalse(
            column_exists(
                self.env.cr,
                "maintenance_request",
                "customer_message_unread_external",
            )
        )

    def test_natural_schema_is_a_no_op_and_leaves_a_seeded_ack_untouched(self):
        # State P: the natural fresh-database schema has neither the
        # external column nor the orphan sort columns — nothing must raise,
        # and a real ack already in place must be left alone.
        #
        # flush_all() first: stored-field writes through the ORM only dirty
        # the cache, so the column would not genuinely hold the seeded value
        # when the migration runs otherwise (same trap TestAckRenameMigration
        # documents).
        seeded_ack = fields.Datetime.now()
        self.request.customer_message_ack_at = seeded_ack
        self.env.flush_all()

        self.migration.migrate(self.env.cr, "19.0.1.0.6")

        self.assertEqual(self._raw_ack(self.request), seeded_ack)

    def test_second_run_changes_nothing(self):
        self._add_external_ack_column()
        self._add_orphan_sort_columns()

        earlier = fields.Datetime.now() - timedelta(days=2)
        later = fields.Datetime.now() - timedelta(days=1)
        self._set_raw(self.request, "customer_message_ack_at", earlier)
        self._set_raw(self.request, "customer_message_external_ack_at", later)
        self.env.flush_all()

        self.migration.migrate(self.env.cr, "19.0.1.0.6")
        after_first_run = self._raw_ack(self.request)
        self.assertEqual(after_first_run, later)

        # Second run: the columns dropped by the first run are gone, so
        # every guard is False and nothing should change.
        self.migration.migrate(self.env.cr, "19.0.1.0.6")

        self.assertEqual(self._raw_ack(self.request), after_first_run)
        self.assertFalse(
            column_exists(
                self.env.cr,
                "maintenance_request",
                "customer_message_external_ack_at",
            )
        )
