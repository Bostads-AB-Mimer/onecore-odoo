# Filter på händelseloggen (chatter) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a four-option filter (Alla / Händelser / Interna noteringar / Kommunikation) to the maintenance request chatter, filtering server-side so pagination stays correct.

**Architecture:** Message category is *derived* from `message_type` + subtype internal flag — no stored column, no migration, works retroactively. One rule table in Python feeds both a non-stored computed field (serialised to the OWL store, used for render-time filtering) and an Odoo `Domain` (used for server-side fetch filtering). The UI is a single-select pill row in the chatter, whose active value lives on the OWL `Thread` record so every fetch path picks it up.

**Tech Stack:** Odoo 19 (Python 3.12), OWL 2 (`patch()` + template inherit via `t-inherit`), SCSS. Tests: `odoo.tests.TransactionCase` with `@tagged("onecore")`.

**Spec:** `docs/superpowers/specs/2026-09-02-mim-1956-chatter-log-filter-design.md`

## Global Constraints

- **All user-facing text is Swedish.** Field labels use `string=`, JS strings use `_t()`, template text is written inline in Swedish (as `tenant_chatter.xml` already does for "Fästa noteringar").
- **Branch:** `feature/mim-1956-filter-pa-handelseloggen-chatter-i-odoo`, based on and targeting `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements`.
- **Category values are exactly** `"event"`, `"internal_note"`, `"communication"`. Swedish labels: `"Händelse"`, `"Intern notering"`, `"Kommunikation"`.
- **Filter is `maintenance.request` only.** Every UI guard checks `props.record?.resModel === "maintenance.request"`; every JS patch no-ops to `super()` when no category is set.
- **Formatters:** Black for Python, Prettier for JavaScript, RedHat XML formatter for XML. Do **not** run Prettier across whole pre-existing files — PR #280 explicitly reverted a repo-wide Prettier run because the repo has no `.prettierrc` and its 2-space default reindents 4-space files end to end, manufacturing conflicts. Format only the lines you add.
- **Merge contention:** `onecore_mail_extension/models/mail_message.py` is also being changed by PR #280 (MIM-1957). Add new code as separate blocks at the end of the class rather than interleaving into existing methods, except for the one-line `_to_store_defaults` addition.
- **`./run_tests.sh` exits 0 even when tests fail.** Every test step below therefore tees output to a log and greps the results line. Never conclude from the exit code alone.
- **Do not commit this plan file.** `docs/superpowers/plans/` stays untracked.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `onecore_mail_extension/models/mail_message.py` (modify) | The single rule table; the computed category field; the `Domain` builder; the `_message_fetch` override; store serialisation |
| `onecore_mail_extension/controllers/thread.py` (modify) | New `/onecore/mail/thread/messages` route carrying the category as a top-level param |
| `onecore_mail_extension/tests/test_log_category.py` (create) | All Python coverage for categorisation, domains, fetch filtering |
| `onecore_mail_extension/static/src/tenant/tenant_thread_patch.js` (create) | Everything `Thread`-scoped: fetch route/params (gate 1), render predicate + empty-state getters (gate 2) |
| `onecore_mail_extension/static/src/tenant/tenant_thread.xml` (create) | `mail.Thread` inherit: filter-aware content condition and empty state |
| `onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js` (modify) | Everything `Chatter`-scoped: pill definitions, active state, click handler |
| `onecore_mail_extension/static/src/tenant/tenant_chatter.xml` (modify) | The pill row markup |
| `onecore_mail_extension/static/src/tenant/tenant_message.scss` (modify) | Pill styling |
| `CLAUDE.md`, `README.md` (modify) | Pointer notes warning that a new `message_type` defaults into Kommunikation |

New files under `static/src/tenant/` need **no manifest change** — the manifest already globs `onecore_mail_extension/static/src/tenant/**/*`.

---

## Task 1: Categorisation rules on `mail.message`

**Files:**
- Modify: `onecore_mail_extension/models/mail_message.py`
- Create: `onecore_mail_extension/tests/test_log_category.py`
- Modify: `CLAUDE.md`, `README.md`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - Module constants `LOG_CATEGORY_EVENT = "event"`, `LOG_CATEGORY_INTERNAL_NOTE = "internal_note"`, `LOG_CATEGORY_COMMUNICATION = "communication"` in `onecore_mail_extension/models/mail_message.py`.
  - `mail.message.onecore_log_category` — non-stored `Selection` field, values as above.
  - `mail.message._onecore_log_category_for(message_type, subtype_internal)` → `str` (`@api.model`). The rule table.
  - `mail.message._onecore_log_category_domain(category)` → `odoo.fields.Domain` (`@api.model`). Raises `ValueError` on an unknown category.
  - `onecore_log_category` present in `_to_store_defaults`, so the OWL store receives it on every message.

- [ ] **Step 1: Write the failing tests**

Create `onecore_mail_extension/tests/test_log_category.py`:

```python
from odoo.tests import TransactionCase, tagged

from ..models.mail_message import (
    LOG_CATEGORY_COMMUNICATION,
    LOG_CATEGORY_EVENT,
    LOG_CATEGORY_INTERNAL_NOTE,
)

# Every message_type the chatter can show, mapped to the category it MUST fall
# into. `user_notification` is excluded because base _message_fetch filters it
# out before it can reach the chatter.
#
# This map is deliberately exhaustive: test_every_message_type_is_classified
# fails when a new type is added to the selection without being listed here.
# That is the guard against a new type silently landing in Kommunikation, i.e.
# in the filter a handläggare reads as "the tenant conversation".
EXPECTED_CATEGORIES = {
    # Base Odoo types (addons/mail/models/mail_message.py:119)
    "email": LOG_CATEGORY_COMMUNICATION,
    "comment": LOG_CATEGORY_COMMUNICATION,  # public subtype; see note below
    "email_outgoing": LOG_CATEGORY_COMMUNICATION,
    "notification": LOG_CATEGORY_EVENT,
    "auto_comment": LOG_CATEGORY_COMMUNICATION,
    "out_of_office": LOG_CATEGORY_COMMUNICATION,
    # ONECore types (onecore_mail_extension)
    "from_tenant": LOG_CATEGORY_COMMUNICATION,
    "receipt_to_tenant": LOG_CATEGORY_COMMUNICATION,
    "tenant_sms": LOG_CATEGORY_COMMUNICATION,
    "tenant_mail": LOG_CATEGORY_COMMUNICATION,
    "tenant_mail_and_sms": LOG_CATEGORY_COMMUNICATION,
    "failed_tenant_sms": LOG_CATEGORY_COMMUNICATION,
    "failed_tenant_mail": LOG_CATEGORY_COMMUNICATION,
    "failed_tenant_mail_and_sms": LOG_CATEGORY_COMMUNICATION,
    "tenant_mail_ok_and_sms_failed": LOG_CATEGORY_COMMUNICATION,
    "tenant_mail_failed_and_sms_ok": LOG_CATEGORY_COMMUNICATION,
}

# `comment` is the one type whose category depends on the subtype: with an
# internal subtype (mail.mt_note = "Logga notering") it is an intern notering,
# with a public one (mail.mt_comment) it is kommunikation. EXPECTED_CATEGORIES
# lists its public reading; the internal one is covered by
# test_log_note_is_internal_note.


@tagged("onecore", "post_install", "-at_install")
class TestOneCoreLogCategory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # res.partner, not maintenance.request: categorisation reads only
        # message_type and subtype_id, so it is model-agnostic, while
        # maintenance.request.create() in this repo calls out to OneCore
        # (management-area population, creation SMS) — slow and network-
        # dependent for no coverage gain. Same choice as test_pin_message.py.
        cls.thread = cls.env["res.partner"].create({"name": "MIM-1956 Test"})
        cls.note_subtype = cls.env.ref("mail.mt_note")
        cls.comment_subtype = cls.env.ref("mail.mt_comment")

    def _message(self, message_type, subtype=None):
        """Create a chatter message with the given type, safely.

        CRITICAL: do not pass a tenant_* type to create(). OneCoreMailMessage
        .create() intercepts any message_type starting with "tenant_" and
        actually dispatches SMS/e-mail through the OneCore API, then rewrites
        the type to a failed_* variant when the call fails. In a test that
        means a live HTTP attempt AND a message_type that is not the one asked
        for.

        So: create with a benign type, then write() the real one. write() is not
        overridden on mail.message, and categorisation reads only the final
        message_type and subtype_id — so this is a faithful fixture.

        create() also reads values["message_type"] unguarded, so it must always
        be supplied.
        """
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.thread.id,
                "body": f"<p>{message_type}</p>",
                "message_type": "notification",
                "subtype_id": subtype.id if subtype else False,
            }
        )
        if message_type != "notification":
            message.write({"message_type": message_type})
        return message

    def test_notification_is_event(self):
        message = self._message("notification", self.note_subtype)
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_EVENT)

    def test_log_note_is_internal_note(self):
        message = self._message("comment", self.note_subtype)
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_INTERNAL_NOTE)

    def test_public_comment_is_communication(self):
        message = self._message("comment", self.comment_subtype)
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_COMMUNICATION)

    def test_tenant_sms_is_communication(self):
        message = self._message("tenant_sms", self.comment_subtype)
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_COMMUNICATION)

    def test_receipt_to_tenant_is_communication(self):
        """MIM-1960's kvittens carries the INTERNAL mail.mt_note subtype but is
        genuinely visible to the tenant on Mina sidor, so it belongs in
        Kommunikation. This is a regression lock on that decision: it passes
        only because the internal-note rule also requires message_type
        == 'comment'."""
        message = self._message("receipt_to_tenant", self.note_subtype)
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_COMMUNICATION)

    def test_message_without_subtype_is_communication(self):
        """Pins NULL handling. A message with no subtype at all must still land
        in exactly one bucket rather than falling through."""
        message = self._message("from_tenant")
        self.assertEqual(message.onecore_log_category, LOG_CATEGORY_COMMUNICATION)

    def test_every_message_type_is_classified(self):
        """Fails the build when a new message_type is added without a
        deliberate category. See the EXPECTED_CATEGORIES comment."""
        # get_values() is the documented accessor and returns the selection
        # AFTER selection_add merging, which is what we need here.
        live_types = set(
            self.env["mail.message"]._fields["message_type"].get_values(self.env)
        ) - {"user_notification"}
        self.assertEqual(
            live_types,
            set(EXPECTED_CATEGORIES),
            "A message_type was added or removed without updating "
            "EXPECTED_CATEGORIES. A new type that is neither 'comment' nor "
            "'notification' falls into Kommunikation by default — decide "
            "whether that is correct, then list it here.",
        )

    def test_expected_categories_match_the_rule_table(self):
        for message_type, expected in EXPECTED_CATEGORIES.items():
            subtype = (
                self.comment_subtype
                if message_type == "comment"
                else self.note_subtype
            )
            message = self._message(message_type, subtype)
            self.assertEqual(
                message.onecore_log_category,
                expected,
                f"{message_type} classified as "
                f"{message.onecore_log_category}, expected {expected}",
            )

    def test_compute_and_domain_agree(self):
        """The rule table has two consumers — the computed field and the search
        domain. This is the test that catches them drifting apart."""
        messages = (
            self._message("notification", self.note_subtype)
            + self._message("comment", self.note_subtype)
            + self._message("comment", self.comment_subtype)
            + self._message("tenant_sms", self.comment_subtype)
            + self._message("receipt_to_tenant", self.note_subtype)
            + self._message("from_tenant")
        )
        MailMessage = self.env["mail.message"]
        for category in (
            LOG_CATEGORY_EVENT,
            LOG_CATEGORY_INTERNAL_NOTE,
            LOG_CATEGORY_COMMUNICATION,
        ):
            domain = MailMessage._onecore_log_category_domain(category)
            by_domain = MailMessage.search(domain & [("id", "in", messages.ids)])
            by_compute = messages.filtered(
                lambda m: m.onecore_log_category == category
            )
            self.assertEqual(
                set(by_domain.ids),
                set(by_compute.ids),
                f"domain and compute disagree for {category}",
            )

    def test_categories_partition_all_messages(self):
        """The three filters must sum to Alla, with no overlap: every message
        visible under exactly one filter, none invisible under all three."""
        messages = self.env["mail.message"]
        for message_type in EXPECTED_CATEGORIES:
            subtype = (
                self.comment_subtype
                if message_type == "comment"
                else self.note_subtype
            )
            messages += self._message(message_type, subtype)
        messages += self._message("comment", self.note_subtype)  # intern notering
        messages += self._message("from_tenant")  # no subtype

        MailMessage = self.env["mail.message"]
        seen = []
        for category in (
            LOG_CATEGORY_EVENT,
            LOG_CATEGORY_INTERNAL_NOTE,
            LOG_CATEGORY_COMMUNICATION,
        ):
            domain = MailMessage._onecore_log_category_domain(category)
            seen += MailMessage.search(domain & [("id", "in", messages.ids)]).ids

        self.assertEqual(
            sorted(seen), sorted(messages.ids), "categories are not a partition"
        )
        self.assertEqual(len(seen), len(set(seen)), "a message matched two categories")

    def test_unknown_category_raises(self):
        with self.assertRaises(ValueError):
            self.env["mail.message"]._onecore_log_category_domain("nonsense")

    def test_category_is_serialized_to_the_store(self):
        """Gate 2 in the browser compares msg.onecore_log_category, so the field
        has to reach the OWL store."""
        self.assertIn(
            "onecore_log_category",
            self.env["mail.message"]._to_store_defaults(None),
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
LOG=/private/tmp/claude-501/-Users-simonkropp-Documents-Prototyp-Projects-Mimer-onecore-odoo/1057561b-6da4-4ff3-b0dd-7bc6ed24c79f/scratchpad/mim1956-t1-red.log
./run_tests.sh 2>&1 | tee "$LOG" | tail -5
grep -E "[0-9]+ failed|[0-9]+ error" "$LOG"
```

Expected: failures in `TestOneCoreLogCategory`, with `AttributeError` / `KeyError` on `onecore_log_category` and on the import of `LOG_CATEGORY_*`. Note the import error may abort collection of the whole module — that still counts as red.

- [ ] **Step 3: Add the rule table, field, compute and domain**

At the **top** of `onecore_mail_extension/models/mail_message.py`, after the existing imports, add `Domain` to the imports and define the constants:

```python
from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Domain
```

```python
# ============================================================================
# HÄNDELSELOGG CATEGORIES (MIM-1956)
# ============================================================================
# Categories for the chatter log filter. Derived, never stored, so the rules
# apply retroactively to every existing message and cannot go stale.
LOG_CATEGORY_EVENT = "event"
LOG_CATEGORY_INTERNAL_NOTE = "internal_note"
LOG_CATEGORY_COMMUNICATION = "communication"
```

Then, at the **end** of the `OneCoreMailMessage` class body (keeping it a
separate block, to stay merge-friendly with PR #280), add:

```python
    # ========================================================================
    # HÄNDELSELOGG CATEGORY (MIM-1956)
    # ========================================================================

    onecore_log_category = fields.Selection(
        [
            (LOG_CATEGORY_EVENT, "Händelse"),
            (LOG_CATEGORY_INTERNAL_NOTE, "Intern notering"),
            (LOG_CATEGORY_COMMUNICATION, "Kommunikation"),
        ],
        string="Loggkategori",
        compute="_compute_onecore_log_category",
        store=False,
    )

    @api.model
    def _onecore_log_category_for(self, message_type, subtype_internal):
        """The single rule table behind the händelselogg filter.

        First match wins. Both consumers — the computed field and
        _onecore_log_category_domain — read these rules, so the server filter
        and the value the OWL store sees cannot drift apart.

        NOTE: Kommunikation is the catch-all. Any NEW message_type that is
        neither "comment" nor "notification" therefore lands in the filter
        handläggare read as the tenant conversation. tests/test_log_category.py
        fails the build until such a type is classified deliberately.
        """
        if message_type == "notification":
            return LOG_CATEGORY_EVENT
        if message_type == "comment" and subtype_internal:
            return LOG_CATEGORY_INTERNAL_NOTE
        return LOG_CATEGORY_COMMUNICATION

    @api.depends("message_type", "subtype_id.internal")
    def _compute_onecore_log_category(self):
        for message in self:
            message.onecore_log_category = self._onecore_log_category_for(
                message.message_type, message.subtype_id.internal
            )

    @api.model
    def _onecore_log_category_domain(self, category):
        """The search-domain twin of _onecore_log_category_for."""
        event = Domain("message_type", "=", "notification")
        internal_note = Domain("message_type", "=", "comment") & Domain(
            "subtype_id.internal", "=", True
        )
        if category == LOG_CATEGORY_EVENT:
            return event
        if category == LOG_CATEGORY_INTERNAL_NOTE:
            return internal_note
        if category == LOG_CATEGORY_COMMUNICATION:
            # Complement of the other two, so the three categories partition
            # the log exactly. DomainNot renders "(...) IS NOT TRUE", which
            # keeps messages with no subtype at all in this bucket — pinned by
            # test_message_without_subtype_is_communication.
            return ~event & ~internal_note
        raise ValueError(f"Okänd loggkategori: {category}")
```

Finally, extend the **existing** `_to_store_defaults` (do not add a second
one) so the list reads:

```python
        return super()._to_store_defaults(target) + [
            "is_dialog_unread_for_side",
            "pinned_by_name",
            "can_pin",
            "onecore_log_category",
        ]
```

- [ ] **Step 4: Add the doc-comment warning at the `selection_add` site**

In the same file, immediately above the existing `message_type = fields.Selection(selection_add=[...])`, add:

```python
    # MIM-1956 — adding a type here has a side effect on the händelselogg
    # filter: anything that is neither "comment" nor "notification" is
    # classified as Kommunikation (see _onecore_log_category_for), i.e. it
    # shows up in the filter handläggare read as the tenant conversation.
    # Decide whether that is right, then add the type to EXPECTED_CATEGORIES in
    # tests/test_log_category.py — the suite fails until you do.
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
LOG=/private/tmp/claude-501/-Users-simonkropp-Documents-Prototyp-Projects-Mimer-onecore-odoo/1057561b-6da4-4ff3-b0dd-7bc6ed24c79f/scratchpad/mim1956-t1-green.log
./run_tests.sh 2>&1 | tee "$LOG" | tail -5
grep -E "[0-9]+ failed|[0-9]+ error" "$LOG"
```

Expected: `0 failed, 0 error(s)`, total test count up by 12 from the pre-task baseline.

**If `test_message_without_subtype_is_communication` or `test_categories_partition_all_messages` fails**, the `~` negation over the `subtype_id.internal` join is not NULL-safe after domain optimisation (spec risk 3b). Replace the `internal_note` domain in `_onecore_log_category_domain` with the id-resolving form, which negates over a plain column:

```python
        internal_subtype_ids = (
            self.env["mail.message.subtype"].sudo()._search([("internal", "=", True)])
        )
        internal_note = Domain("message_type", "=", "comment") & Domain(
            "subtype_id", "in", internal_subtype_ids
        )
```

- [ ] **Step 6: Add the pointer notes to CLAUDE.md and README.md**

In `CLAUDE.md`, under `## Important Notes`, add one bullet:

```markdown
- Adding a `message_type` to `onecore_mail_extension` affects the händelselogg filter (MIM-1956): any type that is neither `comment` nor `notification` is classified as **Kommunikation** and becomes visible in the tenant-conversation filter. See the comment on `message_type` in `onecore_mail_extension/models/mail_message.py` and update `EXPECTED_CATEGORIES` in `onecore_mail_extension/tests/test_log_category.py`
```

In `README.md`, add a new section after `## Migrations` (keeping it short — the
README is otherwise operational):

```markdown
## Message categories in händelseloggen

The chatter filter (Alla / Händelser / Interna noteringar / Kommunikation)
derives its categories from `message_type` and the message subtype — nothing is
stored. **Kommunikation is the catch-all**, so a new `message_type` that is
neither `comment` nor `notification` will show up there by default, in the
filter handläggare read as the tenant conversation.

Before adding a `message_type`, read the comment on the `message_type` field in
`onecore_mail_extension/models/mail_message.py` and classify the new type in
`EXPECTED_CATEGORIES` (`onecore_mail_extension/tests/test_log_category.py`).
The test suite fails until you do.
```

- [ ] **Step 7: Commit**

```bash
git add onecore_mail_extension/models/mail_message.py \
        onecore_mail_extension/tests/test_log_category.py \
        CLAUDE.md README.md
git commit -m "MIM-1956: Kategorisera händelseloggens meddelanden

Härleder kategori (Händelse / Intern notering / Kommunikation) ur
message_type + subtype istället för en ny lagrad kolumn, så reglerna
gäller retroaktivt utan migration.

Kommunikation är avsiktligt catch-all — det gör att tenant_my_pages
(MIM-1957) och receipt_to_tenant (MIM-1960) klassas rätt utan
kodändring. Priset är att en ny message_type hamnar där som default,
vilket EXPECTED_CATEGORIES-testet fångar med rött bygge.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Server-side fetch filtering

**Files:**
- Modify: `onecore_mail_extension/models/mail_message.py`
- Modify: `onecore_mail_extension/controllers/thread.py`
- Modify: `onecore_mail_extension/tests/test_log_category.py`

**Interfaces:**
- Consumes: `_onecore_log_category_domain(category)` and the `LOG_CATEGORY_*` constants from Task 1.
- Produces:
  - `mail.message._message_fetch(domain, *, onecore_log_category=None, **kwargs)` — override accepting the new keyword.
  - `POST /onecore/mail/thread/messages` with params `(thread_model, thread_id, fetch_params=None, onecore_log_category=None)`, returning `{"data": <store result>, "messages": <ids>}` — the same shape as base `/mail/thread/messages`. Task 3's JS calls this route.

- [ ] **Step 1: Write the failing tests**

Append to `onecore_mail_extension/tests/test_log_category.py`:

```python
    def test_message_fetch_filters_by_category(self):
        self._message("notification", self.note_subtype)
        note = self._message("comment", self.note_subtype)
        sms = self._message("tenant_sms", self.comment_subtype)

        MailMessage = self.env["mail.message"]
        fetched = MailMessage._message_fetch(
            domain=None,
            thread=self.thread,
            onecore_log_category=LOG_CATEGORY_INTERNAL_NOTE,
        )["messages"]
        self.assertEqual(fetched.ids, note.ids)

        fetched = MailMessage._message_fetch(
            domain=None,
            thread=self.thread,
            onecore_log_category=LOG_CATEGORY_COMMUNICATION,
        )["messages"]
        self.assertEqual(fetched.ids, sms.ids)

    def test_message_fetch_without_category_is_unchanged(self):
        """Alla must stay byte-identical to today's behaviour."""
        self._message("notification", self.note_subtype)
        self._message("comment", self.note_subtype)
        MailMessage = self.env["mail.message"]
        with_none = MailMessage._message_fetch(
            domain=None, thread=self.thread, onecore_log_category=None
        )["messages"]
        baseline = MailMessage._message_fetch(domain=None, thread=self.thread)[
            "messages"
        ]
        self.assertEqual(with_none.ids, baseline.ids)
        self.assertEqual(len(baseline), 2)

    def test_pagination_applies_after_filtering(self):
        """The reason this filter is server-side. With 40 events ahead of 5
        kommunikation, a client-side filter over a 30-message page would show
        zero. The server must return all 5."""
        for _index in range(40):
            self._message("notification", self.note_subtype)
        for _index in range(5):
            self._message("tenant_sms", self.comment_subtype)

        fetched = self.env["mail.message"]._message_fetch(
            domain=None,
            thread=self.thread,
            onecore_log_category=LOG_CATEGORY_COMMUNICATION,
            limit=30,
        )["messages"]
        self.assertEqual(len(fetched), 5)

    def test_pinned_fetch_ignores_category(self):
        """The 'Fästa noteringar' section stays unfiltered by construction."""
        note = self._message("comment", self.note_subtype)
        note.pinned_at = fields.Datetime.now()
        pinned = self.env["mail.message"]._fetch_pinned_messages(self.thread)
        self.assertEqual(pinned.ids, note.ids)
```

Add `fields` to the test module's imports:

```python
from odoo import fields
from odoo.tests import TransactionCase, tagged
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
LOG=/private/tmp/claude-501/-Users-simonkropp-Documents-Prototyp-Projects-Mimer-onecore-odoo/1057561b-6da4-4ff3-b0dd-7bc6ed24c79f/scratchpad/mim1956-t2-red.log
./run_tests.sh 2>&1 | tee "$LOG" | tail -5
grep -E "[0-9]+ failed|[0-9]+ error" "$LOG"
```

Expected: `TypeError: _message_fetch() got an unexpected keyword argument 'onecore_log_category'` on the three new fetch tests. `test_pinned_fetch_ignores_category` should already pass.

- [ ] **Step 3: Add the `_message_fetch` override**

In `onecore_mail_extension/models/mail_message.py`, inside the
`# HÄNDELSELOGG CATEGORY (MIM-1956)` block added in Task 1, after
`_onecore_log_category_domain`:

```python
    @api.model
    def _message_fetch(self, domain, *, onecore_log_category=None, **kwargs):
        """Adds the händelselogg category filter to the chatter fetch.

        Applied as a plain search domain with no sudo(), so mail.message ACLs
        and record rules still decide what an external contractor sees.
        """
        if onecore_log_category:
            domain = Domain(
                True if domain is None else domain
            ) & self._onecore_log_category_domain(onecore_log_category)
        return super()._message_fetch(domain, **kwargs)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
LOG=/private/tmp/claude-501/-Users-simonkropp-Documents-Prototyp-Projects-Mimer-onecore-odoo/1057561b-6da4-4ff3-b0dd-7bc6ed24c79f/scratchpad/mim1956-t2-green.log
./run_tests.sh 2>&1 | tee "$LOG" | tail -5
grep -E "[0-9]+ failed|[0-9]+ error" "$LOG"
```

Expected: `0 failed, 0 error(s)`.

- [ ] **Step 5: Add the route**

In `onecore_mail_extension/controllers/thread.py`, add a second method to the
existing `OneCoreThreadController` class:

```python
    @http.route(
        "/onecore/mail/thread/messages", methods=["POST"], type="jsonrpc", auth="user"
    )
    def onecore_mail_thread_messages(
        self, thread_model, thread_id, fetch_params=None, onecore_log_category=None
    ):
        # The händelselogg filter (MIM-1956) needs the category to reach
        # _message_fetch, but there is no clean OWL hook that adds a key INSIDE
        # fetch_params, and Thread.rpcParams cannot be used — it is also spread
        # into /mail/message/update_content, where an unknown kwarg raises. So
        # the category travels top-level to this route, which otherwise mirrors
        # base /mail/thread/messages (mail/controllers/thread.py) exactly: same
        # access check, same set_message_done, same Store serialization. Keep it
        # in step with base on Odoo upgrades.
        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        res = request.env["mail.message"]._message_fetch(
            domain=None,
            thread=thread,
            onecore_log_category=onecore_log_category,
            **(fetch_params or {}),
        )
        messages = res.pop("messages")
        if not request.env.user._is_public():
            messages.set_message_done()
        return {
            **res,
            "data": Store().add(messages).get_result(),
            "messages": messages.ids,
        }
```

- [ ] **Step 6: Verify the route is registered**

Restart local Odoo (`./run-local-odoo.sh`) and confirm the route responds
rather than 404s. With the browser open and logged in, in the devtools console:

```js
await odoo.__WOWL_DEBUG__.root.env.services.rpc(
  "/onecore/mail/thread/messages",
  { thread_model: "maintenance.request", thread_id: <an existing ärende id>,
    onecore_log_category: "internal_note" }
);
```

Expected: an object with `data` and `messages` keys, `messages` containing only
intern-notering ids. Compare against `onecore_log_category: null`, which must
return the full log.

- [ ] **Step 7: Commit**

```bash
git add onecore_mail_extension/models/mail_message.py \
        onecore_mail_extension/controllers/thread.py \
        onecore_mail_extension/tests/test_log_category.py
git commit -m "MIM-1956: Filtrera händelseloggen server-side

_message_fetch tar nu emot onecore_log_category, och en egen route
/onecore/mail/thread/messages bär kategorin som top-level-parameter.

Server-side för att chattern paginerar 30 meddelanden i taget: ett
klient-filter hade visat noll kommunikation på ett ärende med 40
händelser före de 5 meddelandena. Det är exakt vad
test_pagination_applies_after_filtering låser.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Thread-level OWL patches (both gates)

**Files:**
- Create: `onecore_mail_extension/static/src/tenant/tenant_thread_patch.js`
- Create: `onecore_mail_extension/static/src/tenant/tenant_thread.xml`

**Interfaces:**
- Consumes: the `/onecore/mail/thread/messages` route from Task 2; the
  `onecore_log_category` field on store messages from Task 1.
- Produces:
  - `thread.onecoreLogCategory` — a plain property on the OWL `Thread` record,
    `undefined` (meaning *Alla*) or one of `"event"` / `"internal_note"` /
    `"communication"`. Task 4 sets it.
  - Thread component getters `onecoreShowContent` and `onecoreEmptyText`, used
    by `tenant_thread.xml`.

There is **no JS test infrastructure in this repo** (`package.json`'s test
script is a stub, zero JS test files), so this task is verified in the browser
via the console rather than by automated tests. Task 5 covers it again through
the real UI.

- [ ] **Step 1: Write the Thread patches**

Create `onecore_mail_extension/static/src/tenant/tenant_thread_patch.js`:

```js
/** @odoo-module **/

import { Thread } from "@mail/core/common/thread_model";
import { Thread as ThreadComponent } from "@mail/core/common/thread";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// MIM-1956 — the händelselogg filter. `thread.onecoreLogCategory` is set by the
// pill row in the chatter (see tenant_chatter_patch.js) and is undefined
// everywhere else, so every patch below delegates straight to super() when it
// is unset. Discuss and all other chatters therefore take untouched code paths.

// --- Gate 1: fetching -------------------------------------------------------
// Routing the fetch through our own route is what makes "Load More" respect the
// filter: both hooks feed fetchMessagesData, which every fetch path uses
// (initial load, fetchMoreMessages, fetchNewMessages). So paging fetches 30
// more OF THAT CATEGORY rather than 30 messages that are then thinned out.
patch(Thread.prototype, {
  get fetchRouteChatter() {
    if (!this.onecoreLogCategory) {
      return super.fetchRouteChatter;
    }
    return "/onecore/mail/thread/messages";
  },

  getFetchParams() {
    const params = super.getFetchParams();
    if (this.onecoreLogCategory) {
      params.onecore_log_category = this.onecoreLogCategory;
    }
    return params;
  },
});

// --- Gate 2: rendering ------------------------------------------------------
// Thread.post ends at addOrReplaceMessage, which pushes a newly posted message
// straight into thread.messages without consulting any domain; bus-delivered
// messages do the same. So logging an intern notering while Kommunikation is
// active would make it pop into a list it does not belong in. The predicate
// below is the second gate. It compares the category serialized onto each
// message by mail.message._to_store_defaults, so the classification rules stay
// in Python only.
patch(ThreadComponent.prototype, {
  get orderedMessages() {
    const messages = super.orderedMessages;
    const category = this.props.thread?.onecoreLogCategory;
    if (!category) {
      return messages;
    }
    return messages.filter((msg) => msg.onecore_log_category === category);
  },

  // Base decides between the message list and the empty state on
  // props.thread.isEmpty, which reads thread.messages — NOT the filtered list.
  // Without this, the leak above yields thread.messages.length === 1, isEmpty
  // false, the content block rendered, the message filtered out by
  // orderedMessages, and an empty area with no empty-state text at all.
  get onecoreShowContent() {
    const thread = this.props.thread;
    if (!thread?.onecoreLogCategory) {
      return !thread.isEmpty || thread.loadOlder || thread.hasLoadingFailed;
    }
    // loadOlder is deliberately dropped here: the server filters by category,
    // so an empty page means there are no older messages of this category and
    // loadOlder is already false.
    return this.orderedMessages.length > 0 || thread.hasLoadingFailed;
  },

  get onecoreEmptyText() {
    switch (this.props.thread?.onecoreLogCategory) {
      case "event":
        return _t("Inga händelser att visa.");
      case "internal_note":
        return _t("Inga interna noteringar att visa.");
      case "communication":
        return _t("Ingen kommunikation att visa.");
      default:
        return _t("Inga meddelanden av den här typen.");
    }
  },
});
```

- [ ] **Step 2: Write the template inherit**

Create `onecore_mail_extension/static/src/tenant/tenant_thread.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">

<t t-name="onecore_mail_extension.OneCoreThread" t-inherit="mail.Thread" t-inherit-mode="extension">

    <!-- Decide list-vs-empty on the FILTERED message list. Identical to base
         when no filter is active (see onecoreShowContent). -->
    <xpath expr="//t[@name='content']" position="attributes">
        <attribute name="t-if">onecoreShowContent</attribute>
    </xpath>

    <!-- Base's "The conversation is empty." reads as data loss under a filter,
         so it is suppressed while one is active and replaced below. -->
    <xpath expr="//t[@name='empty-message']" position="attributes">
        <attribute name="t-if">!props.thread.onecoreLogCategory</attribute>
    </xpath>

    <xpath expr="//t[@name='empty-message']" position="after">
        <t t-if="props.thread.onecoreLogCategory">
            <div class="d-flex flex-column align-items-center">
                <span class="fs-1" style="filter: grayscale(1);">😶</span>
                <span t-esc="onecoreEmptyText"/>
            </div>
        </t>
    </xpath>

</t>

</templates>
```

- [ ] **Step 3: Restart Odoo and verify gate 1 in the console**

```bash
./run-local-odoo.sh
```

Open an ärende with a mixed log. In devtools console:

```js
const env = odoo.__WOWL_DEBUG__.root.env;
const store = env.services["mail.store"];
const thread = store["mail.thread"].get({ model: "maintenance.request", id: <ärende id> });
thread.onecoreLogCategory = "internal_note";
thread.messages = [];
thread.isLoaded = false;
thread.loadOlder = false;
thread.loadNewer = false;
await thread.fetchNewMessages();
thread.messages.map((m) => [m.id, m.onecore_log_category]);
```

Expected: only `internal_note` entries. The Network tab must show the request
going to `/onecore/mail/thread/messages` with `onecore_log_category` in the
payload. Then set `thread.onecoreLogCategory = undefined` and repeat — the
request must go back to `/mail/thread/messages` and return the full log.

- [ ] **Step 4: Verify gate 2 and the empty state in the console**

With `thread.onecoreLogCategory = "communication"` and the log rendered, use
the composer to log an intern notering.

Expected: the note does **not** appear in the list (gate 2 filtered it),
`thread.messages` does contain it, and — if the ärende has no kommunikation at
all — "Ingen kommunikation att visa." is shown rather than a blank area or "The
conversation is empty."

- [ ] **Step 5: Verify no regression outside ärende**

Open Discuss and any other chatter (e.g. a `res.partner` form). Confirm
messages load normally and the Network tab shows `/mail/thread/messages` (or
`/discuss/channel/messages`), never our route.

- [ ] **Step 6: Commit**

```bash
git add onecore_mail_extension/static/src/tenant/tenant_thread_patch.js \
        onecore_mail_extension/static/src/tenant/tenant_thread.xml
git commit -m "MIM-1956: Thread-patchar för händelseloggens filter

Två grindar. Grind 1 (hämtning) routar fetchMessagesData till
/onecore/mail/thread/messages med kategorin, vilket är det som gör att
\"Ladda mer\" respekterar filtret. Grind 2 (rendering) filtrerar
orderedMessages, eftersom Thread.post trycker in nyskrivna meddelanden
i thread.messages utan att bry sig om något domain — annars dyker en
loggnotering upp mitt i Kommunikation.

Tomt läge avgörs på den filtrerade listan, inte thread.isEmpty, som
läser thread.messages och därför missar precis det fallet.

Alla patchar no-oppar till super() utan aktiv kategori, så Discuss och
övriga chattrar tar orörda kodvägar.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: The pill row

**Files:**
- Modify: `onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js`
- Modify: `onecore_mail_extension/static/src/tenant/tenant_chatter.xml`
- Modify: `onecore_mail_extension/static/src/tenant/tenant_message.scss`

**Interfaces:**
- Consumes: `thread.onecoreLogCategory` and the Thread patches from Task 3.
- Produces: the user-facing filter. No interface for later tasks.

- [ ] **Step 1: Add the pill state and handler**

In `onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js`, add to
the existing `patch(Chatter.prototype, { ... })` object. Put these members
after the existing `_fetchPinnedMessages` method:

```js
  // MIM-1956 — händelselogg filter. Single-select, reset to "Alla" on every
  // record open: the filter is component state only, deliberately not
  // persisted, so nobody comes back tomorrow to a log that looks truncated.
  get onecoreLogFilters() {
    return [
      { id: undefined, label: _t("Alla") },
      { id: "event", label: _t("Händelser") },
      { id: "internal_note", label: _t("Interna noteringar") },
      { id: "communication", label: _t("Kommunikation") },
    ];
  },

  showLogFilter() {
    return (
      this.props.record?.resModel === "maintenance.request" &&
      !!this.state.thread?.id &&
      !this.state.isSearchOpen
    );
  },

  isActiveLogFilter(categoryId) {
    return (this.state.thread?.onecoreLogCategory ?? undefined) === categoryId;
  },

  async onClickLogFilter(categoryId) {
    const thread = this.state.thread;
    if (!thread || this.isActiveLogFilter(categoryId)) {
      return;
    }
    thread.onecoreLogCategory = categoryId;
    // Drop the loaded window and re-page from the newest message of the new
    // category. Without the reset, fetchNewMessages would ask for messages
    // after the newest id it already holds — an id from the previous category.
    thread.messages = [];
    thread.isLoaded = false;
    thread.loadOlder = false;
    thread.loadNewer = false;
    await thread.fetchNewMessages();
  },
```

- [ ] **Step 2: Reset the filter when the chatter switches record**

In the same file, extend the existing `load` override so it reads:

```js
  async load(thread, requestList) {
    // Every record opens on "Alla" (MIM-1956). The Thread record is a store
    // singleton that outlives this component, so a stale category would
    // otherwise survive navigation between ärenden.
    if (thread) {
      thread.onecoreLogCategory = undefined;
    }
    await super.load(thread, requestList);
    await this._fetchPinnedMessages(thread);
  },
```

- [ ] **Step 3: Add the pill row markup**

In `onecore_mail_extension/static/src/tenant/tenant_chatter.xml`, inside the
existing `onecore_mail_extension.TenantChatter` template, add a new xpath
before the pinned-messages one:

```xml
    <!-- Händelselogg filter (MIM-1956). Between the topbar and the log, so it
         reads as belonging to the list it filters. Hidden while search is open,
         since search replaces the message list with SearchMessageResult and
         inert pills would be a lie. -->
    <xpath expr="//div[hasclass('o-mail-Chatter-content')]" position="before">
        <div class="o-mimer-LogFilter d-flex flex-shrink-0 overflow-x-auto"
             t-if="showLogFilter()">
            <button t-foreach="onecoreLogFilters" t-as="logFilter" t-key="logFilter.label"
                    class="o-mimer-LogFilter-pill btn btn-sm text-nowrap"
                    t-att-class="isActiveLogFilter(logFilter.id) ? 'active' : ''"
                    t-on-click="() => this.onClickLogFilter(logFilter.id)">
                <t t-esc="logFilter.label"/>
            </button>
        </div>
    </xpath>
```

- [ ] **Step 4: Add the pill styling**

Append to `onecore_mail_extension/static/src/tenant/tenant_message.scss`:

```scss
// MIM-1956 — händelselogg filter pills. Horizontal scroll rather than wrap,
// so a narrow/mobile chatter never pushes the log down a row.
.o-mimer-LogFilter {
    gap: 4px;
    padding: 8px 16px;
    border-bottom: 0.5px solid #DAD7D3;

    .o-mimer-LogFilter-pill {
        border: 0.5px solid #DAD7D3;
        border-radius: 16px;
        background-color: #FFF;

        &.active {
            background-color: #212529;
            border-color: #212529;
            color: #FFF;
        }
    }
}
```

- [ ] **Step 5: Restart Odoo and walk the UI**

```bash
./run-local-odoo.sh
```

Open an ärende with a mixed log and confirm:

1. Four pills render, "Alla" active, log identical to before this branch.
2. Clicking each pill filters the log; clicking the active pill does nothing.
3. Opening search hides the pills; closing it brings them back.
4. Navigating to another ärende resets to "Alla".
5. The pill row scrolls horizontally instead of wrapping when the chatter is
   narrow (drag the form/chatter split, or use a mobile viewport).

- [ ] **Step 6: Commit**

```bash
git add onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js \
        onecore_mail_extension/static/src/tenant/tenant_chatter.xml \
        onecore_mail_extension/static/src/tenant/tenant_message.scss
git commit -m "MIM-1956: Pill-rad för filter i händelseloggen

Fyra pills (Alla / Händelser / Interna noteringar / Kommunikation)
mellan topbaren och loggen, enkelval. Återställs till Alla vid varje
ärendeöppning — Thread är en store-singleton som överlever komponenten,
så en kvarhängande kategori hade följt med till nästa ärende.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full manual verification pass

**Files:** none modified. The deliverable is a verification record.

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: a pass/fail record for the PR description.

The OWL layer has no automated coverage, and PR #280's own "Not verified"
section notes that this untested layer is exactly where its confidentiality bug
lived. This task is the compensating control. Drive it with the
`playwright-cli` skill against local Odoo.

- [ ] **Step 1: Seed a long, mixed log**

Enough messages of one category to force pagination. Via `odoo shell`:

> **Do not create `tenant_*` messages directly.** `OneCoreMailMessage.create()`
> intercepts those types and dispatches a real SMS/e-mail through the OneCore
> API — against a local ärende that means messaging an actual tenant's phone
> number. Create as `notification`, then `write()` the real type, exactly as
> the Python fixture does.

```python
request = env["maintenance.request"].search([], limit=1)
note = env.ref("mail.mt_note")
comment = env.ref("mail.mt_comment")


def seed(count, message_type, subtype, label):
    for index in range(count):
        message = env["mail.message"].create({
            "model": "maintenance.request", "res_id": request.id,
            "body": f"<p>{label} {index}</p>", "message_type": "notification",
            "subtype_id": subtype.id,
        })
        if message_type != "notification":
            message.write({"message_type": message_type})


seed(40, "notification", note, "händelse")
seed(35, "tenant_sms", comment, "sms")
seed(5, "comment", note, "notering")
env.cr.commit()
print(request.id)
```

- [ ] **Step 2: Run the checklist**

Record pass/fail for each:

1. Default is *Alla* on open; the log matches pre-branch behaviour.
2. Each pill filters to only its category.
3. **"Load More" under a filter** — on *Kommunikation* (35 seeded), scroll to
   the bottom and load more. It must page through kommunikation only, never
   showing a page of 30 that thins to 2.
4. **Post an intern notering while *Kommunikation* is active → it must not
   appear.** (Gate 2. This is the highest-value check in the list.)
5. Inverse: with *Interna noteringar* active, send an SMS/Mina sidor message →
   it must not appear.
6. "Fästa noteringar" stays visible and complete under every filter.
7. Open search → pills hidden; close → pills back, previous filter still
   applied.
8. Empty category shows the Swedish line — test both an ärende with no
   messages of that category, and the step-4 case (list emptied by gate 2).
9. Log in as an external contractor: pills work, and a contractor sees no
   message they could not already see under *Alla*.
10. Narrow / mobile chatter: the pill row scrolls horizontally without breaking
    the topbar.

- [ ] **Step 3: Confirm the full Python suite is green**

```bash
LOG=/private/tmp/claude-501/-Users-simonkropp-Documents-Prototyp-Projects-Mimer-onecore-odoo/1057561b-6da4-4ff3-b0dd-7bc6ed24c79f/scratchpad/mim1956-final.log
./run_tests.sh 2>&1 | tee "$LOG" | tail -5
grep -E "[0-9]+ failed|[0-9]+ error" "$LOG"
```

Expected: `0 failed, 0 error(s)`. Quote the results line verbatim in the PR
description — do not paraphrase, and do not rely on the exit code.

- [ ] **Step 4: Open the PR**

Target `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements`.
The description must include: the categorisation rule table, the checklist
results from step 2 with anything unverified stated plainly, the test results
line from step 3, and a note that `mail_message.py` also changes in PR #280
(MIM-1957) so `tenant_my_pages` will need adding to `EXPECTED_CATEGORIES` when
that merges.

---

## Self-Review

**Spec coverage** — every spec section maps to a task:

| Spec section | Task |
|---|---|
| The categorisation (field, rule table, domain helper) | 1 |
| Why the catch-all / partition invariant | 1 (tests) |
| Server design (`_message_fetch`, dedicated route) | 2 |
| Client gate 1 (fetch route/params) | 3 |
| Client gate 2 (render predicate) | 3 |
| Blast-radius guards | 3 (steps 1, 5) |
| Pills | 4 |
| Empty state | 3 (getters + template), 4 (walkthrough), 5 (checklist 8) |
| Left unfiltered (pinned, activities) | 2 (test), 5 (checklist 6) |
| Documentation (inline, CLAUDE.md, README) | 1 (steps 4, 6) |
| Python testing (7 items) | 1, 2 |
| Manual verification (10 items) | 5 |
| Risk 1 mitigation (expectations map) | 1 |
| Risk 3b (negation fallback) | 1 (step 5 fallback) |

Decision 5 (reset to *Alla*) is covered twice on purpose — Task 4 step 2 resets
on record switch, and `showLogFilter()` plus the `load` override keep the pills
and the Thread in agreement.

**Placeholder scan:** no TBD/TODO; every code step carries the actual code;
Task 5's checklist items name concrete actions and expected outcomes.

**Type consistency:** `LOG_CATEGORY_*` constants defined in Task 1 and imported
by name in Tasks 1-2 tests. `_onecore_log_category_for` /
`_onecore_log_category_domain` spelled identically in Tasks 1 and 2.
`onecoreLogCategory` (JS property) and `onecore_log_category` (Python field /
RPC param / store key) used consistently — the JS camelCase name is the Thread
property, the snake_case one is the serialised field and the route parameter.
`onecoreShowContent` / `onecoreEmptyText` defined in Task 3 step 1 and consumed
in Task 3 step 2. `showLogFilter` / `isActiveLogFilter` / `onClickLogFilter` /
`onecoreLogFilters` defined in Task 4 step 1 and consumed in Task 4 step 3.
