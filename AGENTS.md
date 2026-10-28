# onecore-odoo Project Guide

Odoo 19 addons that Bostads AB Mimer uses for ärenden (maintenance requests). Odoo is one half of the ärende flow; the other half is the OneCore monorepo (`Bostads-AB-Mimer/onecore`). Odoo calls OneCore core over HTTP, and OneCore's work-order service reads and writes Odoo over XML-RPC. Read "OneCore integration" before you change a field, a selection value, a stage, a team, a category or a message type.

## Project Structure

| Addon | Role |
|---|---|
| `onecore_maintenance_extension` | Ärenden: search/creation flow, stages, teams, districts, components, time reports. |
| `onecore_mail_extension` | Tenant message types, SMS/email to tenants through core, the tenant composer. |
| `onecore_base_extension` | Login lowercasing, OdooBot off, uninstall protection. |
| `onecore_web_extension` | Frontend patches and dialogs (form, kanban, statusbar). |
| `onecore_ui` | The `mobile` view type used on phones. |
| `onecore_auth` | Keycloak login: creates or re-links users at first login. The only addon that isn't `auto_install`. |
| `onecore_api/` | Plain Python package with `CoreApi`, the HTTP client for core. Not an addon. |

- The addons are `auto_install`, so they get installed together and a missing dependency goes unnoticed. Declare a dependency for every model, field and template your code or migration uses.
- In `onecore_maintenance_extension/models`, `services/` holds plain classes built per call as `Service(env)` that own the business rules, `handlers/` has one search handler per object kind, and `constants.py` holds shared literals.

## Running tests

- Run the tests that cover your change, not the whole suite. CI runs the full suite on every PR and on pushes to main and `epic/**`. Run it locally only when you change code that most features go through: `create()`/`write()` on `maintenance.request`, the stage rules, security, `mail.message.create`, or a migration.
- For a targeted run, copy the command in `run_tests.sh` with a new `-d`, a free `--http-port` and `--test-tags=onecore/<addon>:<TestClass>` (comma-separate several). Check that it reports more than 0 tests: a tag that matches nothing (Git Bash rewrites one that starts with `/`) runs nothing and exits 0.
- `bash run_tests.sh` runs the full suite on a fresh DB, like CI. It binds :8069, so never run it next to a running Odoo there.

## Domain

- **Ärende** = `maintenance.request`. OneCore calls it a work order, with code `od-<id>`.
- **Utrymme** = `space_caption` (Lägenhet, Bilplats, Lokal, Tvättstuga, …). Users can change it.
- An ärende can lack an object, a contract or a tenant.
- **Option vs snapshot records**: a search creates throwaway `maintenance.*.option` rows for the current user, rebuilt on every search. On save they are copied into per-ärende snapshot records (`maintenance.lease`, `maintenance.tenant`, …). One object often has a current and an upcoming lease.
- **Resursgrupp** = `maintenance.team`, seeded from `data/maintenance.team.csv` (rewritten on every upgrade). Kundcenter is xml-id `onecore_maintenance_extension.7`. Teams and users of ended contracts are archived, not deleted.
- **Distrikt / kvartersvärdsområde**: snapshot codes and names from OneCore, written on create, by the assign-team button and by a backfill cron, never on read. Group and pair on codes; names aren't unique.
- **Handläggare** = internal users. **Extern entreprenör** = `group_external_contractor`: they see their team's ärenden, plus ärenden they follow, ordered or are assigned to. Kvartersvärdar and contractors work on phones.
- **Beställande enhet** (`ordering_department`): the orderer's AD department, stamped at create and by a backfill. Mina sidor ärenden get a system parameter's value ("Mina sidor" by default); ärenden a member of Kundcenter creates get "Förmedlat av Kundcenter" unless their category has "Kundcenter beställer" (`kundcenter_orders`, the key categories). Whoever passes an ärende on to another resource group becomes its orderer (`owner_user_id`, labelled "Beställare") and their department is stamped, or left empty for the backfill until they have one (`OrderingDepartmentService.pass_on`). Not passing on: moves by Kundcenter, contractors, the superuser or someone in no resource group, a move to Kundcenter or into the mover's own group, and archived or closed ärenden. It is not a team; Återsänd hands back to the orderer's first resource group by membership.
- **Mina sidor** = the tenant portal. Its ärenden arrive from OneCore with `creation_origin = 'mimer-nu'`; `hidden_from_my_pages` hides an ärende there and blocks messages to it.
- **Archived** (`archive = True`) means cancelled. Exclude archived ärenden from new flows and guards.

### Stages

| xml-id | Name | done | Notes |
|---|---|---|---|
| `maintenance.stage_0` | Väntar på handläggning | False | Unassigned. Setting `user_id` moves it on; clearing it moves an ärende back. |
| `maintenance.stage_1` | Resurs tilldelad | False | |
| `maintenance.stage_3` | Påbörjad | False | |
| `maintenance.stage_4` | Väntar på beställda varor | False | |
| `maintenance.stage_5` | Utförd | **False** | Performed, not closed. Can be skipped. |
| `maintenance.stage_6` | Avslutad | True | The only done stage. OneCore closes ärenden here. |
| `onecore_maintenance_extension.stage_atersand` | Återsänd | False | Clears `user_id` and hands the ärende back to the orderer's team. |

- Identify stages by xml-id, never by name: names differ between languages and databases. Resolve a stage the same way in every path of a feature, through one helper. A missing xml-id makes computes treat the stage as absent and actions refuse with a `UserError`. The existing name lookups are legacy: move their owner to xml-ids rather than copying them.
- "Open" (`stage_id.done = False`) includes Utförd; "active" means not done and not Utförd. Use the search fields on `SearchFieldsMixin` (`is_active_status`, `is_performed`) instead of copying status domains, say which one a filter, favorite or count uses, and when you change what a status means, align every place that uses it.
- Date stamps can be empty on old rows (`closed_date` on legacy Avslutad ärenden). Decide state by stage, and check prod coverage before you build on a stamp.

## OneCore integration

### Odoo → OneCore (`CoreApi`)

- Catch `requests.RequestException` around core calls, not `Exception`, and construct `CoreApi` inside the handling (it may fetch a token). Never report a failed call as success or as "not found" (pattern: `DirectLookupService` raises `LookupFailed` for an outage and returns empty for a miss).
- Core answers 404 when a lookup of one record misses, and 200 with `[]` when a search misses. A 404 from a search means the call failed (a missing route, a wrong base url), in every caller.
- Constants that mirror OneCore (enum names, status filters, codes) are written out literally and keyed by name, so they can be grepped against core's schemas. Never derive them by position (`zip`, `index`) or by transforming strings.
- Core marks many fields nullable and answers 500 for some unknown ids: read with `x.get(k) or default`, and check field names against core's zod schemas.
- Don't call core from computes or form reads; load lazily from a widget through an RPC method.
- HTTP calls are not transactional, and Odoo retries a request after a serialization failure. Make anything sent from `create`/`write`/`message_post` idempotent, or send it after commit. The same goes for anything OneCore can resubmit.
- Odoo ships before OneCore, so tolerate a core that lacks your new route: fall back to the old route on a 404. A joint release doesn't replace this; rollouts and rollbacks happen per service.
- Calls reach real people (creation SMS, tenant SMS/email). Test with your own number.
- Store OneCore ids in explicit Char fields, never in an `"id"` vals key, which the ORM drops.

### OneCore → Odoo (XML-RPC, `odoo-adapter/index.ts` in OneCore's work-order service)

- One integration account creates Mina sidor and inspection ärenden, closes ärenden, posts tenant messages (`from_tenant`) and reads ärenden and messages with fixed field lists. Recognise its writes by `message_type` or `creation_origin`, never by login.
- Its writes skip the form: no onchanges, no option records. Many2one ids arrive as strings; in `create()` Odoo 19 stores them but reads them back empty until `invalidate_recordset()`, and in `write()` they clear the field. Test with the exact payload core sends.
- Core sends no `lang`, so it runs in en_US and finds Kundcenter, Avslutad and categories by name. Never rename those in en_US; category "Besiktning" must exist in every environment. Text rendered during its writes comes out in English unless hardcoded.
- Odoo 19 rejects unknown Selection values and fields. Removing or renaming a value or field core uses breaks Mina sidor.
- Integration keys that aren't fields are popped before `super()`.
- A contract change ships in Odoo first, in every environment, then OneCore, then the apps. Agree field names with OneCore before the first release.
- Every rule in `write()` also hits core's writes, and core's close route answers 200 even when Odoo refused. Say in the PR when a change can refuse a core write.

## Code Standards

### General

- Reuse the owner of a rule: stage rules → `MaintenanceStageManager`; contractor checks → `ExternalContractorService`; OneCore rooms and components → `ComponentOneCoreService`; districts → `ManagementAreaService`; beställande avdelning → `OrderingDepartmentService`; cron-synced badges and contract status → `OneCoreFlagSyncService`; the add/change wizard's lookups → `DirectLookupService`; option → snapshot → `RecordManagementService`; change notes → `FieldChangeTracker`. If the owner is wrong for your case, fix it there instead of writing a second copy.
- A check that previews an action (a button's visibility, a "can I?" method) calls the same helper as the action.
- Code, identifiers, test names, fixtures and comments are in English; UI strings are in Swedish. Comments say what the code does; why it changed, and ticket numbers, go in the PR.
- Remove code your change supersedes, and don't ship code for a follow-up card ahead of time.
- When you add or rename something this file names, update this file in the same PR.

### Security

- Every public method (no leading `_`, not `@api.private`) can be called over RPC by any logged-in user. Start it with `self.check_access(...)`, validate in the method that acts (not only in wizard steps), and make helpers private.
- RPC arguments are untrusted in shape as well as value: check types and raise `UserError`, not `TypeError`. Take only what the server can't derive itself.
- Hiding a button or field is not access control. Enforce on the server too.
- Guards in `create()` check the created records after `super().create()`, not `vals`: `default_*` in the context fills fields the guard never sees.
- The client controls the context. Never use a context key to skip a check.
- A new model that mirrors `maintenance.request`'s access copies its global multi-company rule as well as the group rules.
- The server sets attribution fields (who, when) and ignores client values. Option ids from the client must belong to `env.user`.
- Identity-provider claims are untrusted: require `email_verified`, check types, and fail closed.

### Models

- `write()` on `maintenance.request` is a sequence of steps (validation, stage rules, change capture, `super()`, notes, handback). Read it and put new logic in the step it belongs to.
- A key in `vals` is not a change: forms, multi-edit and OneCore resend unchanged values. Compare with the old value captured before `super().write()`.
- Enforce invariants in the model, not in one widget or button. Stage moves come from the statusbar, kanban drag, list multi-edit, object buttons, create, the Återsänd handback and OneCore. Before adding a guard, list the states where the user can't satisfy it (archived, another Utrymme, unsaved, core callers).
- Add new technical and snapshot fields to `FieldChangeTracker.SKIP_FIELDS`. Code that clears a skipped field logs what it removed.
- Errors name the ärende (`od-<id>`) and say what to do next.
- `env.ref()` and `browse()` ignore `active`, while `search()` and dropdowns hide archived records. Use `active_test=False` when archived teams or users must be found.
- An automatic pick (a refetch, a cron, a backfill, a default saved without a user) chooses among the candidates that qualify, and picks nothing when none does. The best of the rest is not a fallback: an unsigned lease never puts its applicant on an ärende.
- The form search, the add/change wizard, the empty-tenant refetch and OneCore's create build the same lease, tenant and object snapshot. Make the same choice of lease, tenant and object in each, with shared helpers.

### Transactions and performance

- Catching an exception around database work needs `with self.env.cr.savepoint():`, or the transaction is aborted.
- Check-then-insert is a race: let the unique constraint decide. Steps that can be refused together share one savepoint.
- No searches or `env.ref` inside per-record loops. Group writes, count with one `_read_group`, and index Char fields used as lookup keys.
- A cron that calls OneCore in batches commits after each batch (`ir.cron._commit_progress`) and starts no batch that could run past `limit_time_real_cron`. One transaction across many network calls loses the whole run when the worker is killed.

### Onchanges

- `_compute_search` recreates the option records on every search, so `*_option_id` changes even when the hit is the same object. Compare stable ids before you clear anything.
- An onchange that clears data does it only on unsaved records, or logs what it removed: leaving the form auto-saves the clearing. Reset dependent fields on the cleared path too.

### Chatter and messages

- `message_post` with a note notifies every follower here. Notes nobody should be notified about (integration, cron, resubmits) use `_message_log`.
- On `mail.message`, `res_id` means something only together with `model`, and `create` runs for every tracking message: gate extra work on `message_type`.
- A new `message_type` follows the README's "Message categories" section (the tests fail until the type is classified), and goes into OneCore's `MESSAGE_DOMAIN` if tenants should see it. A type that starts with `tenant_` is sent to the tenant.
- A tenant-facing feature is done when it shows on Mina sidor, not just in the chatter.

### Translations, caches and snapshots

- Team and stage names are translated (jsonb). Pin one language when you read them, and never match on them. Hardcode Swedish for text stored at write time.
- Module-level caches are per worker and shared by every database: key them by `dbname`, cache only successful loads, and clear them in tests.
- Snapshots of OneCore data store the stable parts (ids, type, name) and derive positions such as "Fönster 2" on display. Snapshots are never refreshed, except the badges and contract status that `OneCoreFlagSyncService`'s crons keep fresh.

### Frontend

- Async widgets: check the first render, a slow load, a failed load, a retry and paging to another record (the form keeps the widget).
- After a server call, the form and its chatter show the new state on every exit path: success, refusal, error.
- Object buttons on `maintenance.request` run without saving the form. A flow that needs saved data saves first, and never loads over a dirty form.
- Phones use `onecore_ui`'s mobile view; check every change at ~360 px.
- Extend stock views with xpath; never `group_ids` on an extension view. A favorite's domain carries everything it needs, and renaming a filter breaks every action that passes its `search_default_*`.
- Browser storage is per browser on shared devices: wrap it in try/catch, and keep drafts per user and record.
- There are no JS unit tests. Check JS changes in a browser at phone width.

### Tests

- Every test class is `@tagged('onecore')` and its file is imported in `tests/__init__.py`, or the suite skips it silently.
- The default test user (root) is a contractor. Act as a real user with `with_user(...)` and the helpers in `tests/utils/test_utils.py`.
- Test through the path the client uses: `Form` for onchanges, `name_search` for dropdowns, the exact payload core sends.
- Each test must fail without the code it guards: revert the change and watch it go red. Assert the specific error, not just any `UserError`.
- Cover the empty/False case, each contract kind (residence, parking, Lokal), multi-record writes and batch creates.

### Migrations and data

- New fields and models need no migration. Bump `__manifest__.py` only in a PR that adds a migration, strictly above the target branch's version, and keep the higher version when resolving conflicts.
- Releases upgrade every onecore module, and that must not fail: guard records on unique-key models (system parameters), and keep hooks idempotent. Never use `--reinit` on a shared database.
- `noupdate` data (crons, system parameters, favorites) is created once and never updated: get it right before the first release, change it by migration afterwards. Never `<delete>` by id.
- Backfills use `active_test=False` and a pinned language, run in batches and can be re-run. Never mark a row done that the backfill couldn't resolve.
- A new stored field on existing data needs a backfill or a stated "new records only". On `res.users`, it makes Odoo answer 500 between the restart and the upgrade. Time a large migration on a prod copy.

## Reviewing

- Review in a fresh session, not the one that wrote the code: a review run from the writing session shares its blind spots. Review your own fix commits again before pushing; fixes made after a review need a review of their own.
- For every changed rule, find its other copies and callers. List every writer and reader of a changed field, OneCore and planned cards included.
- When a change widens what a value can be or changes what it means (new statuses, a route's error semantics, a new data source), review every consumer of it, including code outside the diff.
- Walk every path into the changed state (form, list, kanban, RPC, context defaults, OneCore) and every exit path out of the flow (success, refusal, error, another tab, the pager, leaving the form). Check what the user sees after each.
- When a finding rests on framework behaviour, read the Odoo source and cite file and line.
- Label each finding blocking, should-fix or nit. Blocking = breaks behaviour, leaks data across users or companies, breaks a Security rule, or makes the upgrade or a OneCore call fail.
- Findings in code the PR didn't touch: mark them pre-existing and suggest a follow-up card. At most 5 nits.
- A finding that has come up in an earlier review becomes a line in this file, in the same PR.
