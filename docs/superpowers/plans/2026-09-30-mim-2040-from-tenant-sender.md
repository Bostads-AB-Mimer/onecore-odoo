# MIM-2040 (extra) — Show the tenant as sender of Mina sidor messages in Odoo

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a tenant writes on an errand from Mina sidor, the Odoo chatter shows the tenant's name instead of "Odoo" (the integration account the message is posted through), whatever that integration account is called in a given setup.

**Architecture:** Identify tenant messages by `message_type == "from_tenant"`, never by author. `mail.message.create()` snapshots the request's tenant name onto a new stored field at write time. A JS patch makes the chatter render that name for `from_tenant` messages, falling back to "Hyresgäst", and always marks them as the tenant's: a "Hyresgäst" badge next to the name, a neutral avatar, no avatar card and "(via Mina sidor)" — so a tenant message can never be mistaken for one from Mimer. `author_id` is left untouched, so nothing downstream changes. An optional controller gate stops the web composer from posting `from_tenant`.

**Tech Stack:** Odoo 19 (Python, OWL), `onecore_mail_extension` addon, `TransactionCase` / `HttpCase` tests tagged `onecore`.

**Spec:** Linear MIM-2040, section "Extra" ("När hyresgäst skickar ett meddelande via mina sidor, så ser det ut i ärendet som att 'Odoo' har skickat meddelandet"). The design choices below were agreed in the investigation; there is no separate spec document.

## Background (read first)

The whole write path, verified 2026-09-30:

- Mina sidor → .NET `POST /api/workorders/update/{id}` → core `POST /work-orders/:id/update` → work-order `POST /workOrders/:id/update` → `addMessageToWorkOrder` in `onecore/services/work-order/src/services/work-order-service/adapters/odoo-adapter/index.ts`, which calls `maintenance.request.message_post` over XML-RPC with `message_type: 'from_tenant'` and **no `author_id`**. Odoo therefore attributes it to the XML-RPC login's partner (odoo@mimer.nu in Mimer's setups — but that login is configuration, `ODOO__USERNAME` in work-order, and must not be assumed).
- Only the message text travels. No layer passes who the tenant is.
- Mina sidor ignores the author on `from_tenant` and shows "Du" (`mina-sidor/src/stores/workorders.js:14`). This change is Odoo-UI-only; the tenant sees nothing different.
- work-order reads `author_id[1]` for `from_tenant` in `messageAuthor` (`odoo-adapter/utils.ts`). **`author_id` must stay a partner** or that breaks — which is why we do not post with `email_from`/no author.
- The chatter renders `message.authorName` (`odoo/addons/mail/static/src/core/common/message_model.js:381`: `author ? author.name : email_from`), the avatar from `Message.authorAvatarUrl` (`core/common/message.js:287`), and opens a user card on click when `hasAuthorClickable()` (`core/web/message_patch.js`).

Precedent for keying on data rather than on the integration user already exists: the customer-message indicator switched from "authored by odoo@mimer.nu" to `message_type` in `onecore_maintenance_extension` migration 19.0.1.0.5, and `OrderingDepartmentService` recognises Mina sidor requests by `creation_origin`, not `create_uid`. No live code outside `docs/` names odoo@mimer.nu.

## Global Constraints

- Work on branch `feature/mim-2040-se-till-att-avsandare-pa-meddelande-till-hyresgast-pa-mina` (PR #291, base `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements`).
- **Never identify the integration user** — no login, no xmlid, no `ir.config_parameter`, no group. Tenant messages are recognised by `message_type == "from_tenant"` only.
- Do not change `author_id` on `from_tenant` messages.
- New field name: `onecore_from_tenant_name` on `mail.message` (Char, stored, `copy=False`). Do **not** reuse `onecore_tenant_author_name` — that is "the sender the tenant sees" on outbound messages, read by work-order, and its help text and 19.0.1.0.1 backfill say it is empty on `from_tenant`.
- Fallback label when no name is stored: `Hyresgäst` (exact string).
- **A `from_tenant` message is always visibly tagged as the tenant's.** When a name is stored the header shows the name followed by a badge reading `Hyresgäst` (exact string, Bootstrap `badge rounded-pill text-bg-info`). When no name is stored the author itself reads `Hyresgäst` and there is no badge, so it never reads "Hyresgäst Hyresgäst". The badge lives in the `mail.Message` template, so it shows in the chatter and in the Odoo inbox alike. Text-only places that print `authorName` (e.g. the messaging-menu preview) show the name without the tag — accepted, they open into the chatter.
- Chatter suffix for `from_tenant`: ` (via Mina sidor)` (exact string, leading space — same as the existing `tenant_my_pages` suffix).
- No backfill migration. Historical `from_tenant` messages show "Hyresgäst". Reason: only the request's *current* tenant is known, which would put the wrong name on old messages after a tenant change.
- No manifest version bump: `onecore_mail_extension` is already at 19.0.1.0.1 on this branch versus 19.0.1.0 on `main`, and nothing here needs a migration script. The new column is created by the release's `odoo-module-upgrade` step.
- Code, comments and identifiers in English; user-facing strings in Swedish; commit messages in English, prefixed `MIM-2040:`.
- Targeted test command (from the repo root, after `source .env`; use a fresh DB name each run):
  ```sh
  source .env && ENV=local python3 "$ODOO_PATH/odoo-bin" \
    --addons-path="$ODOO_PATH/addons,$ODOO_ONECORE_PATH" \
    -d "test_mim2040_$(date +%s)" --db_user="$DB_USER" --db_host="$DB_HOST" --db_port="$DB_PORT" \
    -i onecore_maintenance_extension,onecore_mail_extension \
    --test-enable --stop-after-init --log-level=test \
    --test-tags=/onecore_mail_extension:TestFromTenantSender
  ```
  Drop the throwaway DB afterwards (`dropdb` against the local Postgres only).

## Review Focus

1. **Integration login is not odoo@mimer.nu** (another setup, renamed account, superuser). Expected: same name is stored. Pinned in Task 1 (`test_does_not_depend_on_the_integration_login`, `test_superuser_post_is_labelled_the_same_way`).
2. **Tenant removed or replaced after the message was written** (MIM-1840 removal flow). Expected: the message keeps the name it was written with. Pinned in Task 1 (`test_name_survives_tenant_change`).
3. **Request without a tenant** (vacant object, `manually_vacated`). Expected: nothing stored, chatter shows "Hyresgäst", post does not fail. Pinned in Task 1 (`test_request_without_tenant_stores_nothing`) and Task 2 manual check.
4. **A handläggare's own messages** (log notes, `tenant_my_pages`, SMS). Expected: untouched — own name, own avatar. Pinned in Task 1 (`test_only_from_tenant_messages_get_a_name`) and Task 2 manual check.
5. **A tenant name that looks like a colleague's** (tenant and handläggare share a name). Expected: the "Hyresgäst" badge, the neutral avatar and "(via Mina sidor)" still tell them apart. Checked by hand in Task 2 Step 3.
6. **work-order still reads the message** after the change. Expected: `author_id` is still the integration partner, so `messageAuthor` keeps working and Mina sidor still shows "Du". Pinned in Task 1 (`test_author_id_is_left_alone`) and Task 4 end-to-end.

---

### Task 1: Snapshot the tenant's name on `from_tenant` messages

**Files:**
- Modify: `onecore_mail_extension/models/mail_message.py` — constants block (after `TENANT_AUTHOR_LANG`), field (after `onecore_tenant_author_name`), `_to_store_defaults`, `create()` (after the `TENANT_FACING_MESSAGE_TYPES` block)
- Create: `onecore_mail_extension/tests/test_from_tenant_sender.py`
- Modify: `onecore_mail_extension/tests/__init__.py`

**Interfaces:**
- Produces: module constant `FROM_TENANT_MESSAGE_TYPE = "from_tenant"` in `onecore_mail_extension/models/mail_message.py` (used by Task 3); stored field `mail.message.onecore_from_tenant_name` (Char), serialized to the OWL store as `message.onecore_from_tenant_name` (used by Task 2).

- [ ] **Step 1: Write the failing tests**

Create `onecore_mail_extension/tests/test_from_tenant_sender.py`:

```python
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tools.discuss import Store


@tagged("onecore", "post_install", "-at_install")
class TestFromTenantSender(TransactionCase):
    """MIM-2040 (extra): who wrote a Mina sidor message, as Odoo users see it.

    Mina sidor messages reach Odoo through work-order's XML-RPC login, so their
    author_id is that integration account. Which account that is depends on the
    setup, so nothing here may assume odoo@mimer.nu — every test posts as an
    integration user with an invented login.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        category_id = cls.env.ref("onecore_maintenance_extension.category_1").id
        cls.integration_groups = [
            cls.env.ref("base.group_user").id,
            # Base maintenance rules limit a plain internal user to requests
            # they own or follow; the real integration account is a manager.
            cls.env.ref("maintenance.group_equipment_manager").id,
        ]
        cls.integration_user = cls._integration_user("rpc_integration_a")
        cls.tenant = cls.env["maintenance.tenant"].create(
            {
                "name": "Anna Andersson",
                "contact_code": "P900001",
                "contact_key": "_TESTKEY01",
            }
        )
        cls.request = cls.env["maintenance.request"].create(
            {
                "name": "Trasig kran",
                "maintenance_request_category_id": category_id,
                "space_caption": "Lägenhet",
                "tenant_id": cls.tenant.id,
            }
        )

    @classmethod
    def _integration_user(cls, login):
        return cls.env["res.users"].create(
            {
                "name": f"Integration {login}",
                "login": login,
                "group_ids": [(6, 0, cls.integration_groups)],
            }
        )

    def _post_as_mina_sidor(self, user, record=None):
        """Post the way work-order's addMessageToWorkOrder does over XML-RPC."""
        record = self.request if record is None else record
        return record.with_user(user).message_post(
            body="Kranen droppar fortfarande.",
            message_type="from_tenant",
            body_is_html=True,
        )

    def test_from_tenant_names_the_request_tenant(self):
        message = self._post_as_mina_sidor(self.integration_user)
        self.assertEqual(message.onecore_from_tenant_name, "Anna Andersson")

    def test_does_not_depend_on_the_integration_login(self):
        other = self._integration_user("some_other_setup_integration")
        message = self._post_as_mina_sidor(other)
        self.assertEqual(message.onecore_from_tenant_name, "Anna Andersson")

    def test_superuser_post_is_labelled_the_same_way(self):
        # A setup could post as the superuser; the raw test env is user_root.
        message = self.request.message_post(
            body="Hej", message_type="from_tenant", body_is_html=True
        )
        self.assertEqual(message.onecore_from_tenant_name, "Anna Andersson")

    def test_author_id_is_left_alone(self):
        # work-order's messageAuthor reads author_id[1] on from_tenant, so the
        # author must stay the posting partner.
        message = self._post_as_mina_sidor(self.integration_user)
        self.assertEqual(message.author_id, self.integration_user.partner_id)

    def test_name_survives_tenant_change(self):
        message = self._post_as_mina_sidor(self.integration_user)
        self.request.tenant_id = self.env["maintenance.tenant"].create(
            {
                "name": "Bertil Bengtsson",
                "contact_code": "P900002",
                "contact_key": "_TESTKEY02",
            }
        )
        self.assertEqual(message.onecore_from_tenant_name, "Anna Andersson")
        self.request.tenant_id = False
        self.assertEqual(message.onecore_from_tenant_name, "Anna Andersson")

    def test_request_without_tenant_stores_nothing(self):
        vacant = self.env["maintenance.request"].create(
            {
                "name": "Ledig lägenhet",
                "maintenance_request_category_id": self.request.maintenance_request_category_id.id,
                "space_caption": "Lägenhet",
            }
        )
        message = self._post_as_mina_sidor(self.integration_user, vacant)
        self.assertFalse(message.onecore_from_tenant_name)

    def test_only_from_tenant_messages_get_a_name(self):
        note = self.request.with_user(self.integration_user).message_post(
            body="Intern notering",
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )
        self.assertFalse(note.onecore_from_tenant_name)

    def test_other_model_does_not_borrow_a_request_tenant(self):
        # Same res_id as the request, different model: must not pick up
        # Anna Andersson from an unrelated maintenance.request.
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.request.id,
                "body": "Hej",
                "message_type": "from_tenant",
            }
        )
        self.assertFalse(message.onecore_from_tenant_name)

    def test_name_reaches_the_chatter_store(self):
        # Store.Target() rather than None: see
        # test_log_category.test_category_is_serialized_to_the_store.
        self.assertIn(
            "onecore_from_tenant_name",
            self.env["mail.message"]._to_store_defaults(Store.Target()),
        )
```

Register it in `onecore_mail_extension/tests/__init__.py` (append):

```python
from . import test_from_tenant_sender
```

- [ ] **Step 2: Run the tests to verify they fail**

Run the targeted test command from Global Constraints.
Expected: FAIL/ERROR — `AttributeError`/`KeyError` on `onecore_from_tenant_name` (field does not exist).

- [ ] **Step 3: Implement**

In `onecore_mail_extension/models/mail_message.py`, after `TENANT_AUTHOR_LANG = "sv_SE"` add:

```python
# ============================================================================
# SENDER SHOWN TO ODOO USERS ON MINA SIDOR MESSAGES (MIM-2040, extra)
# ============================================================================
# work-order posts what a tenant writes on Mina sidor through its XML-RPC
# login, so author_id on these messages is an integration account — which one
# is configuration (ODOO__USERNAME) and differs between setups. They are
# therefore recognised by their type, never by who posted them: only the
# work-order service writes this type. Any future integration that relays
# tenant messages must post them with it too.
FROM_TENANT_MESSAGE_TYPE = "from_tenant"
```

After the `onecore_tenant_author_name` field add:

```python
    # MIM-2040 (extra) — who wrote a Mina sidor message, for Odoo users. Only
    # set on from_tenant, where author_id is the integration account rather
    # than the tenant. A snapshot of the request's tenant at write time, so
    # replacing or removing the tenant later cannot rewrite who wrote it. It
    # names the request's tenant, not necessarily the person logged in on
    # Mina sidor — nothing upstream says who that was.
    onecore_from_tenant_name = fields.Char(
        string="Skrivet av hyresgäst",
        copy=False,
        help="Hyresgästen på ärendet när meddelandet skrevs på Mina sidor. "
        "Visas som avsändare i chattern i stället för integrationsanvändaren.",
    )
```

In `_to_store_defaults`, add `"onecore_from_tenant_name",` to the returned list (after `"onecore_log_category",`).

In `create()`, directly after the `if message_type in TENANT_FACING_MESSAGE_TYPES:` block, add:

```python
            # MIM-2040 (extra). Keyed on the type, not on author_id: the
            # integration account that posts these differs between setups.
            # setdefault so a caller that knows the writer can pass it.
            # sudo(): the name must not depend on what the integration account
            # may read.
            if message_type == FROM_TENANT_MESSAGE_TYPE and the_record:
                values.setdefault(
                    "onecore_from_tenant_name",
                    the_record.sudo().tenant_id.name or False,
                )
```

(`the_record` is the lookup already done at the top of the loop: an empty recordset unless `model == "maintenance.request"` and the id is readable, `None` when the maintenance module is absent. Both are falsy, so both skip.)

- [ ] **Step 4: Run the tests to verify they pass**

Run the targeted test command. Expected: all 9 tests in `TestFromTenantSender` PASS.

- [ ] **Step 5: Commit**

```bash
git add onecore_mail_extension/models/mail_message.py onecore_mail_extension/tests/test_from_tenant_sender.py onecore_mail_extension/tests/__init__.py
git commit -m "MIM-2040: record which tenant wrote a Mina sidor message"
```

---

### Task 2: Render the tenant as sender in the chatter

**Files:**
- Create: `onecore_mail_extension/static/src/tenant/tenant_message_model_patch.js`
- Modify: `onecore_mail_extension/static/src/tenant/tenant_message.js` (`getSentAsString`, new `authorAvatarUrl`, new `hasAuthorClickable`)
- Modify: `onecore_mail_extension/static/src/tenant/tenant_message.xml` (tenant badge)

**Interfaces:**
- Consumes: `message.onecore_from_tenant_name` and `message.message_type` on the OWL `mail.message` store record (Task 1).
- Produces: nothing later tasks call.

No JS test harness exists in this repo, so this task is verified by hand against a local Odoo.

- [ ] **Step 1: Patch the message model's author name**

Create `onecore_mail_extension/static/src/tenant/tenant_message_model_patch.js` (picked up by the existing `onecore_mail_extension/static/src/tenant/**/*` asset glob):

```javascript
/** @odoo-module **/

import { Message } from "@mail/core/common/message_model";
import { patch } from "@web/core/utils/patch";

// MIM-2040 (extra). A Mina sidor message is posted through work-order's
// integration account, so its author is that account ("Odoo") rather than the
// tenant. Keyed on the type, not the author: the integration account differs
// between setups. Patched on the model so every place that prints authorName
// (chatter, previews, notifications) agrees.
patch(Message.prototype, {
    get isFromTenant() {
        return this.message_type === "from_tenant";
    },
    // The badge is shown only when a real name is printed; without one the
    // author already reads "Hyresgäst".
    get showsTenantBadge() {
        return this.isFromTenant && Boolean(this.onecore_from_tenant_name);
    },
    get authorName() {
        if (this.isFromTenant) {
            // Messages written before this change carry no name.
            return this.onecore_from_tenant_name || "Hyresgäst";
        }
        return super.authorName;
    },
});
```

- [ ] **Step 2: Tenant badge, neutral avatar, no avatar card, "(via Mina sidor)" suffix**

In `onecore_mail_extension/static/src/tenant/tenant_message.xml`, inside the existing `onecore_mail_extension.Message` template, add as the first xpath:

```xml
        <!-- MIM-2040: mark a Mina sidor message as the tenant's even when it
             carries a name, so it cannot pass for a message from Mimer -->
        <xpath expr="//span[hasclass('o-mail-Message-author')]" position="after">
            <span t-if="message.showsTenantBadge"
                  class="o-mimer-tenant-badge badge rounded-pill text-bg-info me-1">Hyresgäst</span>
        </xpath>
```

In `onecore_mail_extension/static/src/tenant/tenant_message.js`, inside the existing `patch(Message.prototype, { ... })`:

Add after `get canPin()`:

```javascript
  // The avatar and the user card belong to the integration account, not to
  // the tenant who wrote a from_tenant message (MIM-2040).
  get authorAvatarUrl() {
    if (this.message.isFromTenant) {
      return this.store.DEFAULT_AVATAR;
    }
    return super.authorAvatarUrl;
  },
  hasAuthorClickable() {
    if (this.message.isFromTenant) {
      return false;
    }
    return super.hasAuthorClickable();
  },
```

In `getSentAsString()`, change

```javascript
      case "tenant_my_pages":
        return " (via Mina sidor)";
```

to

```javascript
      case "tenant_my_pages":
      case "from_tenant":
        return " (via Mina sidor)";
```

- [ ] **Step 3: Verify by hand in a local Odoo**

Start a local Odoo on this branch with the module upgraded (`./run-local-odoo.sh onecore_mail_extension`, with `-u` if the run script needs it for an existing DB). Then from `odoo-bin shell` on that DB, post as a throwaway integration user (not odoo@mimer.nu):

```python
u = env["res.users"].create({"name": "Integration X", "login": "rpc_x",
    "group_ids": [(6, 0, [env.ref("base.group_user").id, env.ref("maintenance.group_equipment_manager").id])]})
r = env["maintenance.request"].search([("tenant_id", "!=", False)], limit=1)
r.with_user(u).message_post(body="Från Mina sidor", message_type="from_tenant", body_is_html=True)
v = env["maintenance.request"].search([("tenant_id", "=", False)], limit=1)
v.with_user(u).message_post(body="Utan hyresgäst", message_type="from_tenant", body_is_html=True)
env.cr.commit()
```

Open both requests in the browser (hard-refresh so the new asset loads) and check:
- the first shows the tenant's name, then a "Hyresgäst" badge, then "(via Mina sidor)", Odoo's default avatar (`store.DEFAULT_AVATAR`), and clicking name/avatar opens nothing;
- the second shows "Hyresgäst" as the author with **no** badge, otherwise the same;
- the same message in Discuss → Inbox (if you follow the request) also shows the badge;
- temporarily rename the tenant to your own user's name: the two messages are still unmistakable (badge, avatar, suffix);
- a log note and a `tenant_my_pages` message from yourself still show your own name, avatar and user card;
- no errors in the browser console.

- [ ] **Step 4: Commit**

```bash
git add onecore_mail_extension/static/src/tenant/tenant_message_model_patch.js onecore_mail_extension/static/src/tenant/tenant_message.js onecore_mail_extension/static/src/tenant/tenant_message.xml
git commit -m "MIM-2040: show the tenant, not the integration account, on Mina sidor messages"
```

---

### Task 3 (optional): Refuse `from_tenant` from the web composer

`message_type` is one of the parameters Odoo lets the browser pass through `/mail/message/post` (`_get_allowed_message_params`), which is how our composer posts `tenant_*` types. A logged-in Odoo user could therefore hand-craft a `from_tenant` post that displays a tenant's name. Low risk (not reachable from the UI), cheap to close. Limit, state it in the PR: this closes the composer route only; `/web/dataset/call_kw` can still call `message_post` directly, and closing that would mean identifying the integration user, which this plan deliberately avoids.

**Files:**
- Modify: `onecore_mail_extension/controllers/thread.py`
- Create: `onecore_mail_extension/tests/test_from_tenant_composer_gate.py`
- Modify: `onecore_mail_extension/tests/__init__.py`

**Interfaces:**
- Consumes: `FROM_TENANT_MESSAGE_TYPE` from `onecore_mail_extension/models/mail_message.py` (Task 1).

- [ ] **Step 1: Write the failing test**

Create `onecore_mail_extension/tests/test_from_tenant_composer_gate.py`:

```python
from odoo.tests import HttpCase, tagged
from odoo.tests.common import JsonRpcException


@tagged("onecore", "post_install", "-at_install")
class TestFromTenantComposerGate(HttpCase):
    """MIM-2040 (extra): only work-order may write a from_tenant message."""

    def setUp(self):
        super().setUp()
        self.user = self.env["res.users"].create(
            {
                "name": "Sebastian Handläggare",
                "login": "gate_handlaggare",
                "password": "gate_handlaggare",
                "group_ids": [
                    (6, 0, [
                        self.env.ref("base.group_user").id,
                        self.env.ref("maintenance.group_equipment_manager").id,
                    ])
                ],
            }
        )
        self.request = self.env["maintenance.request"].create(
            {
                "name": "Trasig kran",
                "maintenance_request_category_id": self.env.ref(
                    "onecore_maintenance_extension.category_1"
                ).id,
                "space_caption": "Lägenhet",
            }
        )
        self.authenticate("gate_handlaggare", "gate_handlaggare")

    def _post(self, message_type):
        return self.make_jsonrpc_request(
            "/mail/message/post",
            {
                "thread_model": "maintenance.request",
                "thread_id": self.request.id,
                "post_data": {"body": "Hej", "message_type": message_type},
            },
        )

    def test_composer_cannot_post_from_tenant(self):
        with self.assertRaises(JsonRpcException):
            self._post("from_tenant")
        self.assertFalse(
            self.request.message_ids.filtered(
                lambda m: m.message_type == "from_tenant"
            )
        )

    def test_composer_still_posts_ordinary_messages(self):
        result = self._post("comment")
        self.assertTrue(result["message_id"])
```

Append to `onecore_mail_extension/tests/__init__.py`:

```python
from . import test_from_tenant_composer_gate
```

- [ ] **Step 2: Run to verify it fails**

Run the targeted test command with `--test-tags=/onecore_mail_extension:TestFromTenantComposerGate`.
Expected: `test_composer_cannot_post_from_tenant` FAILS (no exception raised); the other passes.

- [ ] **Step 3: Implement**

In `onecore_mail_extension/controllers/thread.py` add imports:

```python
from odoo.exceptions import AccessError
from ..models.mail_message import FROM_TENANT_MESSAGE_TYPE
```

and in `OneCoreThreadController`:

```python
    @http.route()
    def mail_message_post(self, thread_model, thread_id, post_data, context=None, **kwargs):
        # MIM-2040 (extra): from_tenant is what work-order writes on a tenant's
        # behalf, and the chatter shows the request's tenant as its sender. The
        # composer may pass message_type through (that is how tenant_* types
        # are posted), so refuse this one here.
        if post_data.get("message_type") == FROM_TENANT_MESSAGE_TYPE:
            raise AccessError("Meddelanden från hyresgäst kan bara komma från Mina sidor.")
        return super().mail_message_post(
            thread_model, thread_id, post_data, context=context, **kwargs
        )
```

(`@http.route()` with no arguments inherits the parent's routing, including `auth="public"` and `type="jsonrpc"`; `add_guest_to_context` stays on the parent method that `super()` calls.)

- [ ] **Step 4: Run to verify it passes**

Expected: both tests PASS. Also re-run `TestFromTenantSender` — still green.

- [ ] **Step 5: Commit**

```bash
git add onecore_mail_extension/controllers/thread.py onecore_mail_extension/tests/test_from_tenant_composer_gate.py onecore_mail_extension/tests/__init__.py
git commit -m "MIM-2040: keep the web composer from posting as a tenant"
```

---

### Task 4: Full suite, end-to-end check, PR

**Files:**
- Modify: PR #291 description (GitHub)

- [ ] **Step 1: Full onecore test suite**

Run: `./run_tests.sh`
Expected: zero failures. In particular `test_log_category` (its `EXPECTED_CATEGORIES` guard is untouched — no new message type) and `test_tenant_author_name*` still pass.

- [ ] **Step 2: End-to-end through work-order with a non-default login**

Use the `local-e2e` skill. Point the local work-order service at the local Odoo with `ODOO__USERNAME` set to a login other than odoo@mimer.nu (e.g. the `rpc_x` user from Task 2, given a password). Post a message through work-order's `POST /workOrders/:id/update` (or Mina sidor against the local API). Check:
- Odoo chatter shows the tenant's name, the "Hyresgäst" badge, "(via Mina sidor)", Odoo's default avatar;
- `GET` the work order's messages from work-order: the `from_tenant` message still has an `author` (built from `author_id`), and Mina sidor, if running, still shows "Du".

Stop every service and throwaway DB you started when done.

- [ ] **Step 3: Update PR #291**

Push the branch and add to the PR description (English):

```markdown
### Extra: tenant shown as sender of Mina sidor messages in Odoo

Messages a tenant writes on Mina sidor are posted by work-order's XML-RPC login, so the chatter showed "Odoo". They are now recognised by `message_type == "from_tenant"` — never by the integration account, which is configuration and differs between setups — and the chatter shows the request's tenant (snapshotted at write time in `mail.message.onecore_from_tenant_name`) tagged with a "Hyresgäst" badge, a neutral avatar and "(via Mina sidor)", so it cannot be mistaken for a message from Mimer. Older messages show "Hyresgäst". `author_id` is unchanged, so work-order and Mina sidor are unaffected.

Known limit: the name is the request's tenant, not necessarily the person logged in on Mina sidor (shared contracts). Fixing that needs the contact code passed through API → core → work-order.

[If Task 3 was done:] The web composer can no longer post `from_tenant`; `/web/dataset/call_kw` still can, by design.
```
