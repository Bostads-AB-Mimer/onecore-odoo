# Design: Filter på händelseloggen (chatter) (MIM-1956)

**Ticket:** [MIM-1956](https://linear.app/mimer-onecore/issue/MIM-1956/filter-pa-handelseloggen-chatter-i-odoo)
**Branch:** `feature/mim-1956-filter-pa-handelseloggen-chatter-i-odoo`
**Base / PR target:** `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements`
**Date:** 2026-09-02

## Problem

The händelselogg (Odoo chatter) on a maintenance request mixes three
fundamentally different kinds of entry in one undifferentiated stream:
automatic events (stage changes, field changes, added resources), internal
notes between Mimer and external contractors, and actual communication with
the tenant (SMS, e-post, Mina sidor). On a long-running ärende the human
messages drown in the machine-generated ones.

The ticket asks for a filter with four options — *Alla* (default, today's
behaviour), *Händelser*, *Interna noteringar*, *Kommunikation* — and notes that
some form of message categorisation is probably needed first.

## Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **No new stored column, no migration.** Category is derived from `message_type` + subtype | The data already distinguishes all three cases; deriving works retroactively on all historical messages and cannot drift from reality |
| 2 | **Server-side filtering** via a new `_message_fetch` keyword | The chatter paginates 30 messages at a time. Client-side filtering would show 2 of 30 on a long ärende and force repeated "Load More" |
| 3 | **Pill row** above the log, single-select, four pills | Chosen over a topbar dropdown and over multi-select checkboxes: all options visible at a glance, one click to switch, and the ticket describes four mutually exclusive views |
| 4 | **`maintenance.request` only** | Matches the ticket ("händelseloggen" on ärende). On e.g. kundkort/`res.partner` the Kommunikation bucket would be near-empty and the pills pure clutter |
| 5 | **Filter resets to *Alla*** on every record open; nothing persisted | Most predictable, zero storage, matches "Default-värdet" literally. Avoids the failure mode where a user forgets the filter is on *Händelser* and believes messages are missing |
| 6 | **Kommunikation is the catch-all bucket**, not an allowlist of `tenant_*` types | See "Why the catch-all" below — this is the load-bearing choice |
| 7 | **`receipt_to_tenant` (kvittens, MIM-1960) → Kommunikation** | It is outbound and the tenant genuinely sees it on Mina sidor, so it belongs in the tenant conversation, even though it carries the internal `mail.mt_note` subtype |
| 8 | **Filter state lives on the `Thread` record**, not in `Chatter` component state | Every fetch path (initial load, Load More, post-refetch) then picks it up from one hook, so pagination is correct per category. Cost is noted under Risks |

## The categorisation

One **non-stored computed** field on `mail.message` in `onecore_mail_extension`:

```python
onecore_log_category = fields.Selection(
    [("event", "Händelse"),
     ("internal_note", "Intern notering"),
     ("communication", "Kommunikation")],
    string="Loggkategori", compute="_compute_onecore_log_category", store=False,
)
```

Rules, evaluated in order — first match wins:

| Order | Rule | Category | Covers |
|-------|------|----------|--------|
| 1 | `message_type == "notification"` | **event** | Every event log in the codebase (`maintenance.py` loan-product and phone-call notes, `maintenance_workflow_service.py` resource assignment) plus Odoo's own tracking messages — `stage_id` changes via `maintenance.mt_req_status` and other tracked fields via `_message_log` |
| 2 | `message_type == "comment"` and `subtype_id.internal` | **internal_note** | "Logga notering", including the `informs_opposite_party` Mimer⇄leverantör dialogue |
| 3 | anything else | **communication** | `tenant_sms`, `tenant_mail`, `tenant_mail_and_sms`, the `failed_*` and partial-failure variants, `from_tenant` (Mina sidor), `receipt_to_tenant`, `email`, and any `comment` with a public subtype |

`user_notification` is excluded upstream by base `_message_fetch` and never
reaches the chatter.

Alongside the compute, one classmethod returning the equivalent Odoo domain:

```python
@api.model
def _onecore_log_category_domain(self, category):  # -> Domain
```

Both the compute and the domain read **one shared rule definition**, so the
server filter and the per-message value cannot drift apart. That single source
of truth is why the category is a field at all — see "Two gates" below.

### Why the catch-all (decision 6)

Rule 3 makes the three categories an **exact partition** of what *Alla* shows:
every message is visible under exactly one filter, and no message can be
invisible under all of them. That is a testable property.

It is also what makes the categorisation survive new channels, which this epic
is actively adding:

- **MIM-1957** (PR #280, in review) adds `tenant_my_pages`. Under rule 3 it
  becomes Kommunikation with no code change.
- **MIM-1960** (PR #281, merged into the epic) added `receipt_to_tenant`.
  Likewise.

Had Kommunikation been written as an explicit allowlist of `tenant_*` types —
the tempting version — both would be neither `notification` nor internal
`comment`, so they would have fallen out of *all three* filters and been
visible only under *Alla*. Silently.

Rule ordering also matters: rule 2 requires `message_type == "comment"`, so
`receipt_to_tenant`'s internal `mail.mt_note` subtype cannot misroute it into
Interna noteringar.

## Server design

One override in `onecore_mail_extension/models/mail_message.py`:

```python
@api.model
def _message_fetch(self, domain, *, onecore_log_category=None, **kwargs):
    if onecore_log_category:
        domain = Domain(True if domain is None else domain) & self._onecore_log_category_domain(
            onecore_log_category
        )
    return super()._message_fetch(domain, **kwargs)
```

`Domain` is imported from `odoo.fields`, as base `mail.message` does.

### A dedicated route, for testability

**Superseded during planning:** an earlier version of this spec claimed no
controller change was needed, because base `mail_thread_messages` forwards
`**fetch_params` straight into `_message_fetch`. That is true, but there is no
clean JS hook that adds a key *inside* `fetch_params`:
`Thread.fetchMessagesData` builds the whole `rpc()` call in one expression, so
injecting a key means copying its ~12 lines into our patch — duplicated
upstream logic in the one layer this repo has no automated tests for.

`Thread.rpcParams` looked like the intended extension point (portal overrides
it for tokens) and is spread in at top level, but it is **rejected**: it is also
spread into `/mail/message/update_content` (`message_model.js:582`) and other
message-action RPCs, where an unknown top-level kwarg would raise. Using it
would break message editing.

So the category travels as a **top-level** parameter to a dedicated route:

- `POST /onecore/mail/thread/messages` in
  `onecore_mail_extension/controllers/thread.py`, accepting
  `(thread_model, thread_id, fetch_params=None, onecore_log_category=None)`,
  mirroring base `mail_thread_messages` — same `_get_thread_with_access` check,
  same `set_message_done`, same `Store` serialisation — and passing the
  category into `_message_fetch`.

This trades ~12 lines of copied *JavaScript* for ~8 lines of copied *Python*.
Worth it: the Python half is covered by the test suite, the JS half would not
be. It does mean re-entering `controllers/thread.py`, which the pinned-message
feature owns, but the addition is a separate route rather than a modification.

The filter is applied through a normal `search()` as the requesting user, with
no `sudo()` anywhere, so mail.message ACLs and record rules still govern
visibility. An external contractor filtering on Kommunikation sees only the
messages they were already allowed to read.

Our own `_fetch_pinned_messages` passes no category and is therefore unaffected
by construction.

## Client design

### Two gates, and why both are needed

**Gate 1 — fetch.** The active category is stored on the Thread record as
`thread.onecoreLogCategory`. Two small `Thread.prototype` patches, neither
containing copied upstream logic:

- `get fetchRouteChatter()` — returns `/onecore/mail/thread/messages` when a
  category is set, otherwise `super`.
- `getFetchParams()` — adds `onecore_log_category` when a category is set,
  otherwise `super`.

Because both feed `fetchMessagesData`, this covers initial load,
`fetchMoreMessages` ("Load More") and `fetchNewMessages`, so paging fetches 30
more *of that category* rather than 30 messages that are then thinned out.

`getFetchParams()` has one other caller, `store.searchMessagesInThread` — and
it calls `thread.getFetchRoute()` too, so **both** hooks are on the search path.
An active category would therefore silently scope the search to that category
while the pills are hidden, leaving the user no way to see why a term is not
found. Composing the two is a deliberate follow-up (risk 6), so opening search
instead **clears** the filter: `Chatter.onClickSearch` is patched to reset the
category and refetch. See risk 6 for the consequence.

On pill click: clear `thread.messages`, reset `isLoaded` / `loadOlder` /
`loadNewer`, refetch.

**Gate 2 — render.** `Thread.post` ends at `addOrReplaceMessage`, which pushes
a newly posted message straight into `thread.messages` without consulting any
domain; bus-delivered messages do the same. So logging an intern notering while
*Kommunikation* is active would make it pop into a list it does not belong in.
The Thread component's `orderedMessages` getter — the single render-time hook —
is patched with a predicate.

Because `onecore_log_category` is serialised onto every message via
`_to_store_defaults`, that predicate is `msg.onecore_log_category === active`:
one string compare, with the classification rules still living only in Python.
This is the whole reason the category is a serialised field rather than rules
re-implemented in JavaScript.

### Blast-radius guards

Both Thread patches are global — they apply to Discuss and every other chatter,
not only ärende. Each therefore opens with a no-op guard: if
`thread.onecoreLogCategory` is unset, delegate straight to `super()`. Combined
with the `maintenance.request` guard on the pills, nothing outside ärende can
ever set the category, so every other chatter takes an untouched code path.

### Pills

Added to the existing `onecore_mail_extension.TenantChatter` inherit in
`tenant_chatter.xml`, xpathed between `o-mail-Chatter-top` and the pinned
section. Guarded on `props.record?.resModel === "maintenance.request"`, in the
same style as the existing acknowledge button and pinned section.

Hidden while `state.isSearchOpen`: search swaps the `Thread` component out for
`SearchMessageResult`, so visible-but-inert pills would be a lie. And because
search runs through the same two fetch hooks (see above), opening search clears
the filter — so closing search returns the pills to *Alla*, not to the previous
filter.

Styling goes in the existing `tenant_message.scss`. Strings follow existing
convention in this module — raw Swedish in the template (as "Fästa noteringar"
already is), `_t()` in JS.

### Empty state

Base renders "The conversation is empty." when `thread.isEmpty`. Two problems
under a filter:

1. The text reads as data loss when the ärende clearly has messages.
2. `isEmpty` is computed from `thread.messages`, **not** from the filtered
   render list. So posting an intern notering while *Kommunikation* is active
   leaves `thread.messages.length === 1` → `isEmpty` false → base renders the
   content block → gate 2 filters the message out → an empty content area with
   no empty-state message at all.

The empty state must therefore be driven by the **filtered** list rather than
by base's unfiltered `isEmpty`, and show a filter-aware Swedish line (e.g.
"Inga meddelanden av den här typen.").

The way that is done is to **narrow `Thread.isEmpty` itself** (a patch on the
Thread *model*): with a category active it reports empty unless some message in
`thread.messages` carries that category. Base's own condition on the
`name="content"` node (`!props.thread.isEmpty or props.thread.loadOlder or
props.thread.hasLoadingFailed`) is then left completely untouched and does the
right thing on its own. Patching `isEmpty` is base-sanctioned: base's
`mail/static/src/discuss/core/public_web/thread_model_patch.js` narrows it the
same way with `super.isEmpty`. The guard is a plain no-op when no category is
set, so every thread outside ärende keeps base's behaviour — see risk 3c for
why touching base's `t-if` was rejected.

### Left unfiltered, deliberately

- **"Fästa noteringar"** — separate RPC, and always-visible is the entire point
  of pinning.
- **"Planerade aktiviteter"** and scheduled messages — not log entries.

## Files touched

| File | Change |
|------|--------|
| `onecore_mail_extension/models/mail_message.py` | Category field + compute, shared rule table, `_onecore_log_category_domain`, `_onecore_sanitize_log_category`, `_message_fetch` override, one entry in the existing `_to_store_defaults`, and the `EXPECTED_CATEGORIES` expectations map |
| `onecore_mail_extension/controllers/thread.py` | New `/onecore/mail/thread/messages` route |
| `onecore_mail_extension/static/src/tenant/tenant_thread_patch.js` (new) | Thread model patches (`fetchRouteChatter`, `getFetchParams`, `isEmpty`) and Thread component patches (`orderedMessages`, `onecoreEmptyText`), all with no-op guards |
| `onecore_mail_extension/static/src/tenant/tenant_thread.xml` (new) | `mail.Thread` inherit — suppresses base's empty-state node under an active filter and adds the Swedish one next to it. Deliberately does **not** touch base's `name="content"` `t-if` (see risk 3c) |
| `onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js` | Pill state, click handler, shared reset (`_onecoreSetLogCategory`), visibility getter, `onClickSearch` clearing the filter |
| `onecore_mail_extension/static/src/tenant/tenant_chatter.xml` | Pill row (with `role="group"` / `aria-pressed`), filter-aware empty state |
| `onecore_mail_extension/static/src/tenant/tenant_message.scss` | Pill styling |
| `onecore_mail_extension/tests/test_log_category.py` (new) | See Testing |
| `README.md` | Documentation note — see below |

Only `mail_message.py` collides with PR #280. `CLAUDE.md` is **not** in this
table: it is gitignored in this repo (`.gitignore`) and has never been tracked,
so it cannot ship with the PR — see Documentation.

## Documentation

Risk 1 is a trap for the *next* developer, not for this implementation, so it
needs to be written down where that developer will be standing. Three places
that actually ship, weighted by hit rate:

1. **An inline comment on the `message_type` `selection_add` list** in
   `mail_message.py` — canonical and detailed, because a developer adding a
   type is literally editing that list. MIM-1960 already set this precedent
   with its comment explaining why `receipt_to_tenant` is deliberately not
   prefixed `tenant_`. The comment states that any type that is neither
   `comment` nor `notification` falls into the **Kommunikation** filter by
   default, that this makes it visible to anyone filtering the tenant
   conversation, and that the `EXPECTED_CATEGORIES` map must be updated to
   classify it deliberately.
2. **`EXPECTED_CATEGORIES` itself, at the bottom of `mail_message.py`** — the
   build-failing half. It lives in the model file rather than in the test file
   precisely so it sits next to the rule table it guards, in the file the
   developer already has open;
   `test_log_category.py::test_every_message_type_is_classified` imports it and
   fails on any live `message_type` missing from it.
3. **`README.md`** — a short "Message categories in händelseloggen" note. The
   README is otherwise operational (dev setup, deploy, migrations), so this
   stays brief and points at the inline comment rather than restating the rule
   table.

Only item 1 carries the full explanation; the other two point at it, so there
is one place to update if the rules ever change.

**Not `CLAUDE.md`.** An earlier version of this spec listed a pointer in
`CLAUDE.md` → "Important Notes" as one of the three places. That does not work
here: `CLAUDE.md` is gitignored in this repo and has never been tracked, so a
note added there is invisible in the PR and absent from every other machine and
agent that checks the branch out. The three above are the ones that ship.

## Testing

### Python — `onecore_mail_extension/tests/test_log_category.py`

`@tagged("onecore")` on `TransactionCase`, matching `test_pin_message.py`.

1. One case per category for the compute.
2. `receipt_to_tenant` → communication, as an explicit regression lock on
   decision 7.
3. **Partition invariant.** Iterate the live `message_type` selection (minus
   `user_notification`), post one message of each, assert every message lands
   in exactly one category and that the three domains together return all of
   them.
4. **Exhaustive expectations map.** `EXPECTED_CATEGORIES`, a hardcoded
   `{message_type: category}` dict in `mail_message.py`, plus an assertion that
   every value in the live selection appears in it. A new message type then
   *fails the build* until someone classifies it deliberately. Without this,
   rule 3 would silently absorb new types — see Risk 1. The assertion is
   **one-directional**: `live_types - EXPECTED_CATEGORIES` must be empty, but
   the reverse (a listed type that is not installed) is only logged. `sms` and
   `snailmail` arrive through `auto_install`, not through the `-i` list, and
   that list differs between `run_tests.sh` and `.github/workflows/test.yml` —
   a set-equality assertion would make CI fragile for a reason unrelated to
   what this test guards.
5. **Compute-vs-domain agreement.** For a mixed set,
   `_onecore_log_category_domain(c).search()` must return exactly the messages
   whose computed category is `c`. Guards drift between the two consumers of
   the rule table.
6. **Pagination after filtering.** Seed 40 events + 5 kommunikation, fetch
   communication with `limit=30`, expect 5. Fails under any client-side
   implementation; this is the concrete justification for decision 2.
7. `_fetch_pinned_messages` returns the same set regardless of category.
8. **Bogus category from the client.** `onecore_log_category` reaches the
   server as a top-level route parameter, so
   `_onecore_sanitize_log_category` validates it against the field's selection
   and drops unknown values (the fetch then behaves as *Alla*). Without that,
   `_onecore_log_category_domain`'s `ValueError` would turn a malformed request
   into a 500 plus a traceback. The `ValueError` itself is kept, and still
   tested, as the signal for a genuine programmer error in server code.

### JavaScript — no automated coverage available

`package.json`'s test script is a stub and the repo contains no JS test files.
PR #280's own "Not verified" section flags that this untested OWL layer is
exactly where its confidentiality bug lived. The OWL half therefore gets a
manual pass against local Odoo, seeding a long log via `odoo shell`:

1. Default is *Alla* on every open; *Alla* is byte-identical to today.
2. Each pill filters correctly.
3. **"Load More" under a filter** — needs >30 messages of one category to be
   meaningful. This is the case client-side filtering fails.
4. **Log a notering while *Kommunikation* is active → it must not appear.**
   (Gate 2.)
5. Inverse: send SMS / Mina sidor while *Interna noteringar* is active.
6. Pinned section visible under every filter.
7. Open search under an active filter → pills hide, the filter is cleared, and
   the search covers the whole log (not just that category); close search →
   pills are back on *Alla* and the full log is loaded. See risk 6.
8. Empty category shows the Swedish line, not "conversation is empty" — test
   both the no-messages case and the case in step 4.
9. External contractor login — pills work, record rules still govern what is
   readable.
10. Narrow / mobile chatter — pill row scrolls horizontally without breaking
    the topbar.

## Risks and known limitations

**1. Rule 3 cuts both ways — the sharpest flaw in this design.** The catch-all
is what makes `tenant_my_pages` and `receipt_to_tenant` classify correctly for
free. But it also means a genuinely *new kind* of message that is neither
communication nor event silently becomes Kommunikation. Concretely: if someone
later adds an internal integration message with a custom `message_type` (not
`comment`, not `notification`), it lands in a tenant-facing filter. The
partition test cannot catch this — the message is still in exactly one bucket.
Mitigated on two fronts: the exhaustive expectations map (test 4), which
converts silent misfiling into a failing build, and the documentation note (see
Documentation), which warns the developer *before* they add the type rather
than after CI rejects it. The test is the load-bearing half — it is the only
thing standing between rule 3 and a confidentiality-shaped bug, so it should
not be dropped later as "just a test".

**2. Filter state on the Thread record is shared state.** The Thread is a store
singleton per record. Two `Chatter` components mounted on the same ärende
simultaneously (form chatter plus an aside, or the `onecore_ui` mobile
renderer) would share one `onecoreLogCategory`: filtering one filters the
other, and the reset-and-refetch would blow away the other's list. This is the
accepted cost of decision 8 — it is what makes "Load More" respect the filter.
Believed to be unreachable today because the ärende chatter is single-instance,
but it is an assumption about the view layer, not an invariant.

**3. Two upstream-private surfaces are being extended.** We add a keyword-only
argument to `_message_fetch` and forward `**kwargs`, relying on the base
signature. And `/onecore/mail/thread/messages` mirrors the body of base
`mail_thread_messages` — if upstream changes that route (an extra access check,
a different serialisation), our copy silently keeps the old behaviour. Both are
internal Odoo details that could shift on a version upgrade, and both will fail
at fetch time rather than at import time. The mitigation is that the copy is
small, adjacent to base in the same file, and exercised by the Python tests.

**3b. `subtype_id.internal` negation must be verified, not assumed.** The
Kommunikation domain is `~event & ~internal_note`, and `internal_note` contains
a related-field condition. **Verified during implementation, and not the way
this risk originally guessed:** `DomainNot._to_sql` (which renders
`(...) IS NOT TRUE`) is never reached, because `DomainNot._optimize_step`
applies De Morgan first (`odoo/orm/domains.py`). `~internal_note` therefore
becomes `message_type != "comment" OR subtype_id NOT ANY (internal = True)`,
and the NULL-safety comes from `Many2one.condition_to_sql`, which wraps a
negated `any` as `(field IS NULL OR field NOT IN (...))` whenever
`can_be_null` (`odoo/orm/fields_relational.py`). `mail.message.subtype_id` is
nullable, so `can_be_null` holds and subtype-less messages stay in
Kommunikation. Pinned by `test_compute_and_domain_agree` and
`test_categories_partition_all_messages`, which both include a subtype-less
`comment` — the only case where that relational branch decides on its own. If
those ever fail, the fallback is to resolve internal subtypes to ids first
(`Domain("subtype_id", "in", internal_subtype_ids)`), which negates over a plain
column instead of a join.

**3c. The `mail.Thread` template inherit is global — and expression
attributes cannot be composed on the client side.**
`t-inherit-mode="extension"` mutates `mail.Thread` itself, so
`tenant_thread.xml` reaches every thread render in the app — Discuss, chat
windows, mailboxes, livechat — not just ärende. That rules out
`position="replace"` on base's `name="content"` `t-if`: it would freeze a copy
of base's expression in this repo, and an upstream tweak to it would silently
keep the old behaviour app-wide.

An earlier attempt tried to *compose* onto that `t-if` instead, with
`<attribute name="t-if" add="..." separator="and"/>`. **That does not work
here, and fails silently.** Composition of expression attributes exists only in
the **server-side** inheriter: `odoo/tools/template_inheritance.py` special-cases
`PYTHON_ATTRIBUTES` (`t-if`, `t-elif`, `readonly`, `invisible`, …), validates
the separator and emits `(old) and (new)` with both operands parenthesised.
Static OWL asset templates such as this one are inherited **in the browser** by
`addons/web/static/src/core/template_inheritance.js`, whose `modifyAttributes`
has no such case: it does `splitAndTrim(oldValue, separator)`, appends the added
value, and `values.join(separator)` — splitting on the literal substring and
rejoining with **no spaces and no parentheses**. So base's `!props.thread.isEmpty
or props.thread.loadOlder or props.thread.hasLoadingFailed` plus
`add="onecoreShowContent" separator="and"` compiled to
`… or props.thread.hasLoadingFailedandonecoreShowContent`, gluing two
identifiers into one lookup that is simply `undefined`. No OWL error, clean
console, condition never evaluated — the render guard was dead code, and a
filter that yielded nothing produced a completely blank händelselogg.

The approach actually used therefore **never overrides base's condition at
all**: `Thread.isEmpty` is narrowed in a model patch (see Empty state), so
`!props.thread.isEmpty or …` keeps working verbatim for every thread. Only the
`empty-message` node is still touched, and its `t-if` is set to a plain value
rather than composed — `add=` there would be a latent trap, not protection, for
exactly the reason above.

Residual exposure: the remaining xpath still depends on base's
`name="empty-message"` marker, and it resolves against the *post-patch* tree,
since base's own `mail/static/src/core/web/thread_patch.xml` replaces that node
and re-emits it inside a `<t t-else="">` — asset-order-dependent and not visible
from our file, so it is called out in a comment there. And because `isEmpty` is
now patched globally, its other consumers were checked: base's
`core/common/thread.xml`, `core/web/thread_patch.xml` (guarded on
`model === 'mail.box'`) and the `mark-all-read` / `unstar-all` thread actions
in `core/web/thread_actions.js` (guarded on the inbox/starred mailboxes) — none
of which can ever see a thread with a log category set.

**4. Acknowledge refetch only refreshes the filtered subset.**
`_acknowledgeSignals` calls `thread.fetchMessages()` to re-serialise
`is_dialog_unread_for_side` so the orange highlight clears. Under an active
filter that refetch is scoped to the current category, so highlights on
messages outside it are not refreshed until the filter changes. Cosmetic and
self-correcting, but worth knowing before someone debugs it.

**5. Switching filters loses scroll position.** Reset-and-refetch always
returns to the newest 30 of the new category. Expected behaviour, but a user
who has scrolled far back under *Kommunikation* and switches to *Alla* starts
over at the top.

**6. Search and filter do not compose — and had to be actively prevented.** A
user cannot search *within* Kommunikation. Composing them would be nearly free
— both paths go through `_message_fetch`, and the search flow already carries an
`is_notification` filter param — but it is deliberately out of scope here. Most
likely first follow-up request once handläggare use this.

Note that "do not compose" is not the default: `store.searchMessagesInThread`
calls **both** `thread.getFetchRoute()` and `thread.getFetchParams()`, the two
hooks gate 1 patches, so leaving a category set would have scoped the search to
it silently — with the pills hidden, so the user could not see why their term
was not found. `Chatter.onClickSearch` therefore clears the category and
refetches. The visible consequence: **closing search leaves the pills on
*Alla*** rather than restoring the previous filter. Accepted as the smaller
surprise of the two, and it disappears when composition is implemented.

**7. No count badges on the pills.** A user cannot tell a category is empty
without clicking it. Would require extra count RPCs; judged not worth it for a
first version.

**8. *Händelser* may be the least useful filter in practice.** Every tracked
field change posts a `notification`, so on an active ärende this bucket is
likely to dominate the log by volume. The filters that deliver the ticket's
actual value are *Interna noteringar* and *Kommunikation*. Worth checking with
David after release whether *Händelser* wants sub-filtering or is fine as a
"show me the machine noise" escape hatch.

**9. Subtype no longer implies audience.** `receipt_to_tenant` carries
`mail.mt_note` (internal) but is classified as tenant-facing Kommunikation, and
is genuinely visible to the tenant on Mina sidor. Any future code that infers
"is this internal?" from the subtype alone will be wrong. This predates
MIM-1956 but our rule table is the first place that dependency is written down.

**10. Test and seed fixtures must never `create()` a `tenant_*` message.**
`OneCoreMailMessage.create()` intercepts any `message_type` starting with
`tenant_` and dispatches a real SMS/e-mail through the OneCore API, then
rewrites the type to a `failed_*` variant when the call fails. A fixture that
creates `tenant_sms` directly therefore makes a live HTTP attempt *and* ends up
with a different `message_type` than it asked for — and seeding a local ärende
this way would message a real tenant's phone number. Fixtures create as
`notification` and then `write()` the intended type; `write` is not overridden.
`create()` also reads `values["message_type"]` unguarded, so it must always be
supplied.

**11. Three-way merge contention on `mail_message.py`.** PR #280 (MIM-1957) is
in review against the same file, and MIM-1960 has just landed in it. Our
additions go in as separate blocks rather than interleaved to keep the conflict
resolvable.

## Out of scope

- Per-message category badges in the chatter.
- Combining filter with search (risk 6).
- Count badges on pills (risk 7).
- Persisting the filter across records or sessions (decision 5).
- Any chatter other than `maintenance.request` (decision 4).
