# Helpdesk ticket forms (per-category question sets)

Date: 2026-10-22
Module: `onecore_helpdesk` (Odoo 19 Community, on top of vendored OCA `helpdesk_mgmt`)
Status: v1 built in `onecore_helpdesk` on 2026-10-22, portal intake and add-on forms added 2026-10-27 (tests written, suite not yet run)

## Intent

Mimer's IT helpdesk is moving from the current intranet tool to Odoo. The
current tool uses predefined intake forms per issue type so that the
reporter answers specific questions up front (see the "Felanmälan IT"
form: port replicator number, which program, who is affected, how severe).
We want the same thing in Odoo: a configurable set of extra questions
whose answers are stored on the ticket, without a code change every time
IT wants to add or reword a question.

## Decision in one paragraph

Use Odoo's built-in Properties mechanism (`fields.PropertiesDefinition`
on a container record, `fields.Properties` on the ticket). Introduce a new
model `helpdesk.ticket.form` that belongs to a ticket category and holds
the question definition. A ticket points at one form, and the ticket's
`properties` field reads its definition from that form. Title and
description stay as the required free text on every ticket; the form only
adds questions on top. Categories keep their OCA meaning (team routing,
reporting, portal listing) and a category may have zero, one or many forms.

## Goals

- IT admins can create and edit the questions for a form from the Odoo UI
  (the gear icon on the properties widget) with no deploy.
- Forms ship with the module as seed data so a fresh install has the
  current intranet forms.
- Answers are stored on the ticket, visible on the ticket form, and
  searchable / groupable in list and pivot views.
- The form definition doubles as the contract for any external intake
  (OCA portal form or a ONECore frontend): render the definition, post the
  answers back.

## Non-goals

- No custom form builder, no custom JSON schema, no key-value answer table.
  Odoo Properties already provides editor, widget, validation and search.
- No subcategories. A "form" is the level below category. The OCA
  `parent_id` on categories is left as is and not used by us.
- No inheritance or merging of definitions between forms. Each form's
  definition is the complete set of extra questions.
- Rendering the form in a ONECore frontend is out of scope for this
  design. The data model must make it possible (see "External intake"
  below). The OCA portal page was extended on 2026-10-27, see "Portal
  intake".
- Deriving priority from "who is affected / how severe" is out of scope.
  Those become ordinary selection properties; an automation can be added
  later.

## Anti-goals (would make this a failure even if it works)

- Repurposing `category_id` to mean "form". Everything keyed on category
  (team `category_ids`, reporting, portal) must keep working unchanged.
- Modifying the vendored OCA folders. All changes live in
  `onecore_helpdesk`.
- Tickets created by email being rejected because they have no form.

## Background: how Properties work (for the builder)

- `fields.Properties(definition="<m2o_field>.<definition_field>")` on a
  model. The path must be exactly one hop (Odoo asserts
  `definition.count(".") == 1`). The ticket stores only `{name: value}`
  JSON; the definition (label, type, options, default) is read from the
  container record on every read.
- `fields.PropertiesDefinition()` on the container holds a JSON list of
  property specs. Allowed types in Odoo 19: boolean, integer, float, text,
  char, html, date, datetime, monetary, many2one, many2many, selection,
  tags, separator.
- Writing accepts either the full list (what the web client sends) or a
  plain dict `{name: value}` (convenient for controllers and APIs).
- **There is no "required" concept.** `PropertiesDefinition.ALLOWED_KEYS`
  in Odoo 19 is name, string, type, comodel, default, suffix, selection,
  tags, domain, view_in_cards, fold_by_default, currency_field. A seeded
  definition with a `required` key fails at install. The gear-icon editor
  has no required toggle, and the server never validates answers. See
  "Required questions" below.
- When the container changes on an existing record, the web client warns
  the user that the old answers no longer match.
- OCA already declares `properties` on `helpdesk.ticket` with
  `definition="team_id.ticket_properties"` and
  `ticket_properties = fields.PropertiesDefinition()` on
  `helpdesk.ticket.team`. The team is the wrong container for us: Mimer has
  one IT team and several forms.
- Reference implementation in core: `project.task.task_properties` with
  `definition='project_id.task_properties_definition'`.

## Data model

### New model `helpdesk.ticket.form`

| Field | Type | Notes |
|---|---|---|
| `name` | Char, required, translate | Shown to the reporter, e.g. "Dator / arbetsplats" |
| `sequence` | Integer | Order within the category |
| `active` | Boolean, default True | Archive instead of delete |
| `category_id` | Many2one `helpdesk.ticket.category`, required, ondelete restrict | The category this form belongs to |
| `company_id` | Many2one `res.company` | Follow the category's convention (default current company) |
| `ticket_properties` | PropertiesDefinition | The question set |
| `show_in_portal` | Boolean, default True | Mirrors the category flag; reserved for the external intake work |
| `description` | Text or Html, optional | Intro text shown above the questions (the screenshot has an explanatory paragraph before the impact questions) |

Record name is `name`. Access: read for all helpdesk users, write for the
helpdesk manager group (`helpdesk_mgmt.group_helpdesk_manager`). Portal
users only see forms with `show_in_portal`, via the same record rule
pattern OCA uses for teams.

### Changes to `helpdesk.ticket` (via `_inherit` in onecore_helpdesk)

- `form_id = fields.Many2one("helpdesk.ticket.form", ondelete="restrict", tracking=True)`
  with a domain restricting to forms of the current `category_id`
  (`[("category_id", "=", category_id)]`).
- Redeclare `properties = fields.Properties(definition="form_id.ticket_properties", copy=True, precompute=False)`.
  Redeclaring a field in an inherited model replaces the OCA declaration;
  the team-level definition becomes unused.
- Compute on `category_id`: keep a form that belongs to the category,
  preselect the category's only active form, otherwise clear.
- Constraint: if `form_id` is set, `form_id.category_id` must equal
  `category_id`.
- **Category and form rule (uniform, decided 2026-10-26, widened
  2026-10-27).** Every ticket needs a category, and a form when the category
  has any, whoever creates it. Enforced in the ticket form view (`required`)
  and server side in `create` and `write`. There is no superuser exemption:
  automated callers get defaults instead. A ticket created without any
  category gets the team's default category in `create`; an explicit empty
  category is rejected. Only the context key `skip_ticket_form_rules`
  bypasses the rule, and only `message_new` sets it, for a team without a
  default category, so an email never bounces. `write` checks only when
  the category, form or answers are in the payload, so stage moves and other
  edits on an old ticket without answers still save; the client-side check
  mirrors this (new record, or answers/form changed). A write that carries a
  definition change (the gear editor) skips the required-answer check, since
  adding a required question is configuration, not answering. Agents are not
  exempt: a
  category with one form preselects it, so the rule rarely costs them a
  click. If IT later wants to re-categorise email tickets without a form,
  the rule is one method to relax.
- **Email tickets get the team's default category.** New field
  `default_category_id` on `helpdesk.ticket.team`, applied in the ticket's
  `create` to any payload without a category (so also automations and
  scripts). Seeded as "Övriga IT-frågor" for the IT team, a category
  with no forms, so email stays free text and still satisfies the rule.
- A payload with `form_id` but no `category_id` (an API client, or an agent
  attaching a form to an email ticket) gets the category derived from the
  form: always on `create`, and on `write` only for tickets that have no
  category yet. A ticket that already has a category keeps it, so a
  mismatching form fails the constraint instead of silently moving the
  ticket.
- The form record has no editor for its own definition (core Odoo has no
  widget for a `PropertiesDefinition` field). Questions are defined from a
  ticket using the form via the gear icon, and are saved on the form when
  that ticket is saved. The form view explains this.
- Odoo recomputes `properties` whenever the form changes and keeps only the
  answers whose keys exist in the new definition (none when the form is
  cleared). Because property changes are not tracked, the ticket posts the
  old form's answers as a chatter note whenever the form changes and there
  were answers. This covers re-categorisation (which clears the form) and
  switching forms within a category.

### Changes to `helpdesk.ticket.category` (via `_inherit`)

- `form_ids = fields.One2many("helpdesk.ticket.form", "category_id")`
- `form_count` computed, for display.

No change to the OCA category fields or hierarchy.

### `helpdesk.ticket.team.ticket_properties`

Left in place, unused. Hide it in the team form view from onecore_helpdesk
so admins do not configure it by mistake.

## Views

- Ticket form view: `category_id` required; `form_id` next to it, shown
  when the category has forms or the ticket already has one, required when
  the category has forms. The OCA properties widget is currently
  `invisible="not team_id"`; change (via xpath) to `invisible="not form_id"`.
- Team form view: `default_category_id` after the team's categories.
- Ticket list / search: `form_id` as optional column and as a filter and
  group-by.
- Form model: list and form views under Helpdesk > Configuration >
  "Formulär". The form view shows name, category, sequence, active,
  description, and the properties definition. Builder's call whether to
  expose the raw definition editor on the form record or rely on the gear
  icon from a ticket; the gear icon alone is acceptable for v1.
- Category form view: a tab or smart button listing its forms.

## Seed data

Shipped in `onecore_helpdesk/data/helpdesk_it_form_data.xml` with
`noupdate="1"`, same pattern as the existing team/category data. Property
`name` keys must be set explicitly and be stable, readable identifiers
(e.g. `port_replicator`, `program`, `affected_scope`, `impact`) so that
external intake and reporting can rely on them. Do not let the UI
auto-generate hex names for seeded forms.

Initial forms, based on the current intranet "Felanmälan IT" form:

- Category **Felanmälan IT**, form **Felanmälan IT** (one form for now;
  IT can split it later):
  - `port_replicator` char, label "Numret på portreplikatorn (ex 4137-12)"
  - `program` selection, label "Om program, vilket?". Options to
    be taken from the current intranet list; builder may seed a
    reasonable starting list (Teams, Outlook, Word, Excel, Odoo, Övrigt)
    and IT adjusts in the UI.
  - `separator` with the impact explanation text
  - `affected_scope` selection, label "Vilka påverkas?". Options
    from the current intranet form; if unavailable, seed: "Bara jag",
    "Min avdelning", "Hela Mimer". (Required in the intranet form; see
    "Required questions".)
  - `impact` selection, label "Hur drabbas du/ni?". Options from
    the current intranet form; if unavailable, seed: "Kan arbeta som
    vanligt", "Kan arbeta med begränsningar", "Kan inte arbeta".
- Screenshots of the remaining intranet forms are expected from the
  product owner; when they arrive, this section is extended with one seeded
  form per screenshot, same conventions.
- Other categories (Beställning av utrustning, Beställning av Teams,
  Felanmälan hyresgäster och sökande, Beställning IT i fastigheter,
  Övriga IT-frågor): no forms seeded. They behave as plain title +
  description until IT adds forms in the UI.

The exact labels and option lists are content, owned by IT. The builder
should make them easy to change (they are, since they live in the
definition JSON) and should not block on getting them perfect.

## Required questions

The intranet form marks "Vilka påverkas?" and "Hur drabbas du/ni?" as
mandatory. Odoo Properties cannot express that (see Background). Options:

- (a) **Accept optional everywhere.** Seed them as plain selections. Agents
  and reporters can leave them blank. No extra code.
- (b) **Build required into Properties.** Extend the allowed definition
  keys via `_additional_allowed_keys_properties_definition`, add a ticket
  constraint, and patch the OWL definition editor and widget. This is the
  custom form builder work the non-goals rule out.
- (c) **Enforce at the intake edge only.** Add `required_property_names`
  (a list of property names) on `helpdesk.ticket.form`. The backend widget
  stays unenforced; the future portal / ONECore intake reads the list and
  makes those inputs mandatory. Small, and keeps the backend free for
  triage of email tickets that never had answers.

**Decision (product owner, 2026-10-27): (b), built.** Required answers are
part of this version after all; the blank entry on every selection made the
gap visible immediately.

What exists:

- Server: `models/base.py` allows a boolean `required` key on property
  definitions through `_additional_allowed_keys_properties_definition` and
  validates it in `_validate_properties_definition`. The ticket enforces it
  in `_check_required_answers`, called from create and from write whenever
  category, form or answers change, for non-superuser callers (same
  exemption as the category rule). Separators and booleans never count;
  0 is an answer.
- Client (`static/src/properties/`): an "Obligatorisk" checkbox in the
  question editor; an asterisk on the label; the blank entry of a required
  selection becomes a hidden, disabled placeholder so the question starts
  empty but cannot be set back to empty; and a patch on the record's
  validity check so saving is blocked with Odoo's normal "Missing required
  fields" notice and a red outline on the unanswered question.
- Seed: "Vilka påverkas?" and "Hur drabbas du/ni?" are required.
- `question_summary` marks required questions with `*`.

Maintenance: the client patches extend Odoo web templates and `Record`;
check them on each Odoo upgrade.

## Odoo quirk: questions on an unsaved ticket

Odoo's `onchange` only returns a field when its value differs between the
before and after snapshots. Unanswered properties are not stored, so with
questions that have no defaults the stored answers are `{}` both before and
after picking a form, `properties` is left out of the response, and the
questions only appear after the ticket is saved. Clearing the form leaves
stale questions on screen for the same reason. Odoo's own tests for this
flow all use defaults, which is why it goes unnoticed upstream.
`onecore_helpdesk` overrides `onchange` on the ticket to return the
questions (with carried-over answers and defaults applied) whenever
`form_id` changed, and an empty list when it was cleared. Covered by
onchange tests.

## Display for agents

The OCA ticket form already renders the properties widget as label/value
pairs in two columns directly above the notebook containing the
Description tab. Pointing the field at the form is enough for "Vilka
påverkas: Bara jag" to appear above the free text. Odoo 17+ forms are
always in edit mode, so values show in their input widgets (a selection
shows as a dropdown with the chosen value), not as plain text. A flatter
read-only summary block is not part of v1; add it only if agents ask.

Two gaps the builder should close in v1 because they matter more to IT
than styling:

- **New-ticket notification.** The email IT receives when a ticket is
  created does not include property answers. Include the form name and
  the answered properties (label: value, skipping empties) in whatever
  notification template onecore_helpdesk uses for new tickets. If no such
  template exists yet, note it and leave it for the notification work.
- **Chatter tracking.** Property changes are not tracked. Acceptable for
  v1; `form_id` itself is tracked.

## Portal intake (built 2026-10-27)

Requesters create tickets at `/my/tickets` → `/new/ticket`, the OCA portal
page. `onecore_helpdesk/controllers/portal.py` extends the OCA controller
and `views/portal_templates.xml` the two OCA templates:

- The category select is always shown and required, whatever the OCA
  company setting "Select category in Helpdesk portal" says, because the
  category rule is uniform. The team select stays governed by the OCA
  setting (off by default); the ticket goes to the team that owns the
  category (`team.category_ids`) when no team was chosen.
- A form select follows the category. Each portal form (`active`,
  `show_in_portal`) renders its intro text and questions in its own
  `<fieldset data-form-id>`, hidden and disabled until chosen. The script
  in `static/src/portal/new_ticket_form.js` (an Odoo 19 public Interaction)
  filters the forms by category, preselects a category's only form and
  enables the chosen fieldset. Disabled fieldsets are neither validated by
  the browser nor posted.
- Inputs are named `question_<property name>`. Supported question types:
  char, text, integer, float, boolean, date, datetime (posted as the
  requester's wall clock, stored in UTC), selection (required ones get a
  non-selectable placeholder instead of a blank choice, like the backend
  widget) and tags. many2one, many2many, html and monetary are skipped in
  rendering and parsing; a portal form should not use them.
- The controller turns the posted inputs into the `properties` dict and
  creates the ticket; the ticket rules (category, form, required answers)
  apply as for everyone.
  A rejected submit rolls back in a savepoint and shows the page again with
  the message and the entered values. A posted form that is hidden from
  the portal or belongs to another category is rejected.
- The portal ticket page shows the form in the sidebar and the answered
  questions as "Svar från formuläret" above the description, via
  `helpdesk.ticket._displayed_answers()` (same formatting as the chatter
  snapshot).

Tests: `tests/test_portal_forms.py` (HttpCase as the portal user).

## Add-on forms (built 2026-10-27)

Some questions repeat across every form of a category but not across the
team: the intranet "Påverkan" section (who is affected, how badly) belongs
to every IT fault form and to none of the order forms. Instead of copying
it into each form, it is a form record of its own that categories point at:

- `helpdesk.ticket.form.kind`: `form` (picked by the requester, belongs to
  a category) or `addon` (no category of its own; categories reference it
  through `helpdesk.ticket.category.addon_form_id`, several may share one).
  Both kinds have name, intro text, questions and ticket count, and both
  appear in the Formulär list. A constraint keeps a form in a category and
  an add-on out of one.
- The ticket gets a second block, `addon_properties`, whose definition is
  the add-on's. A Properties definition may only follow one relation, so
  the category's add-on is mirrored on the ticket as the stored related
  field `addon_form_id` and the block follows that. Everything written for
  the form block (required answers, the onchange fix, the chatter snapshot
  on container change, the client patches, the portal) applies to both;
  the model keeps the pairs in `QUESTION_BLOCKS`.
- Ticket form view: each block under a rule, with the form's name as title
  and its intro text below, then the questions. Questions are edited with
  the gear icon on the block of any ticket that uses the form. The add-on's
  record shows which categories use it; a form's record and the Formulär
  list show the add-on that comes with it.
- Portal: the form dropdown lists ordinary forms only. The add-on of the
  chosen category renders under the form's questions with its name and
  intro, inputs named `addon_question_<name>`. An add-on follows its
  category into the portal regardless of its own `show_in_portal` flag.
- Seed: add-on "Påverkan" with the intranet explanation as intro and the
  required questions "Vilka påverkas?" and "Hur drabbas du/ni?", referenced
  by the IT fault category. The Felanmälan IT form keeps only the port
  replicator and program questions and has no intro text.
- The mail gateway now always skips the ticket rules: an email can neither
  pick a form nor answer questions. The team's default category is still
  applied in `create`.
- Tried and rejected on the way: questions on the category record itself
  (not reachable from the Formulär list, and a second place to maintain
  questions), and a separator question as the block's title (rendered as a
  foldable uppercase group header, splitting the questions across columns).

Existing databases: the form and category records are noupdate, so the
move of the Påverkan questions into an add-on must be done by hand or by
recreating the database.

## External intake (design constraint for other intakes)

Whatever else renders the form outside the Odoo backend (a ONECore
frontend) should:

1. List active categories, then active `show_in_portal` forms for the
   chosen category.
2. Render `form.ticket_properties` (the definition JSON) as inputs.
3. Create the ticket with `category_id`, `form_id`, `name`,
   `description`, attachments, `properties` and `addon_properties` as
   dicts `{property_name: value}`.
4. Rely on the server for category, form and required answers; they are
   enforced for every caller.

The data model in this document must not make any of that harder. Nothing
else is required now.

## Testing expectations

Odoo `TransactionCase` tests in `onecore_helpdesk/tests`, tagged
`onecore`, following the existing `test_it_team_config.py` style:

- Seed data loads: the Felanmälan IT form exists, belongs to the right
  category, and its definition contains the expected property names.
- A ticket with that form exposes those properties; writing a dict of
  answers round-trips.
- Changing a ticket's category to one with a single form preselects it;
  changing to a category whose forms do not include the current form
  clears `form_id`.
- The constraint rejects a form from another category.
- A ticket created through the mail gateway (reuse `EMAIL_TEMPLATE`) has
  no form and is created without error.

## Left to the builder

- Exact field names on the ticket for the "category has forms" indicator
  used by the view.
- Whether to show the definition editor on the form record or only via the
  gear icon.
- Menu placement and icons.
- Translations (sv_SE) for new labels, following whatever the module does
  today.
- Migration: none needed; no existing tickets use team-level properties.

## Rejected alternatives

- **Custom JSON definition table + key-value answer table.** Rebuilds the
  editor, widget, validation and search that Properties already provide.
- **Definition on the category, no form model.** Works for one form per
  category, but IT wants several forms per category.
- **Use OCA subcategories as forms.** Same shape, but it would make
  `category_id` mean "form" on tickets and break everything keyed on
  category (team routing, reporting, portal lists).
- **One team per form.** Teams are an assignment concept; wrong axis.
- **Odoo `survey` module.** A form builder, but built for questionnaires,
  and linking survey responses to tickets is awkward.
