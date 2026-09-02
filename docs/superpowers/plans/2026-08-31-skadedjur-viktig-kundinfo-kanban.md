# Skadedjur & viktig kundinfo i kanbanvyn — Implementation Plan (MIM-1959)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "Spärr skadedjur" badge visible in the kanban overview alongside "Viktig kundinfo", and keep both flags refreshed after a case is created — without ever firing a OneCore call per kanban card.

**Architecture:** A new lean onecore endpoint returns every rental id carrying an active block of a given reason in one call. Odoo turns `requires_pest_control` into a stored field written only by the create path and a cron, and a second cron refreshes `maintenance.tenant.special_attention` through the existing batch contacts endpoint. Both syncs write only records whose value actually changed, so a quiet run costs no `UPDATE` at all. This mirrors `ManagementAreaService` and honours the MIM-1869 rule: no synchronous HTTP on any read path.

**Tech Stack:** Odoo 19 (Python, OWL/XML views), onecore (TypeScript, Koa, Prisma, Jest/supertest)

**Spec:** `docs/superpowers/specs/2026-08-31-skadedjur-viktig-kundinfo-kanban-design.md`

## Global Constraints

- **Two repos, one worktree each.** Repo `onecore-odoo`: branch `feature/mim-1959-visa-skadedjur-viktig-kundinfo` off `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements`. Repo `onecore`: branch `feature/mim-1959-rental-blocks-rental-ids` off `epic/mim-1983`. Commit in the repo the task names; never mix repos in one commit.
- **Tasks 1–2 are onecore. Tasks 3–9 are onecore-odoo.** The onecore endpoint must merge and deploy before the Odoo cron goes live.
- **All user-facing strings are Swedish.** Field labels, filters, badges.
- **Odoo field definitions always include `string=`.**
- **Formatters:** Black for Python, Prettier for TypeScript/JavaScript, RedHat XML formatter for XML.
- **Never write to `maintenance.request` from a sync without `skip_change_tracking`.** `write()` posts chatter notes otherwise (`models/maintenance.py:1185-1191`); spec decision 3 is that flag flips are silent.
- **The block reason literal is `"SKADEDJUR"`** — a caption, matching `ResidenceBasicInfo.tsx:48` and the existing Odoo compute.
- **Odoo's archived flag on `maintenance.request` is `archive` (Boolean, True = archived), not `active`.** The open-request domain is `[("closed_date", "=", False), ("archive", "=", False)]`.

### Test commands

| What | Command |
|---|---|
| onecore property service | `cd services/property && npx jest --config jest.config.js <pattern>` — note the package script is named `test:borked`, there is no plain `test` |
| onecore core | `cd core && npx jest <pattern>` |
| Odoo module tests | `./run_tests.sh` from the repo root (runs the whole `onecore` tag) |
| One Odoo test class | append `--test-tags=/onecore_maintenance_extension:<ClassName>` to the `odoo-bin` invocation inside `run_tests.sh` |
| Odoo `onecore_api` tests | `pytest onecore_api/tests/test_core_api.py` — plain pytest, **not** run by CI |

`run_tests.sh` sources `.env`, which is gitignored and therefore absent from a fresh worktree. Before the first Odoo test run: `cp ../../../.env .env` and set `ODOO_ONECORE_PATH` to the worktree path, otherwise the tests run against the main checkout.

---

## File Structure

**onecore** (Tasks 1–2)
- Modify `services/property/src/types/residence.ts` — query-param schema for the new route
- Modify `services/property/src/adapters/residence-adapter.ts` — `getRentalIdsWithBlock()`
- Modify `services/property/src/routes/residences.ts` — `GET /residences/rental-blocks/rental-ids`
- Create `services/property/src/tests/rental-blocks-rental-ids.test.ts`
- Modify `core/src/adapters/property-base-adapter/index.ts` — proxy adapter
- Modify `core/src/services/property-base-service/index.ts` — proxy route
- Create `core/src/services/property-base-service/tests/rental-blocks-rental-ids.test.ts`

**onecore-odoo** (Tasks 3–9)
- Modify `onecore_api/core_api.py` — three fetch methods
- Modify `onecore_api/tests/test_core_api.py`
- Modify `onecore_maintenance_extension/models/maintenance.py` — field flip, compute deletion, create hook, cron methods
- Create `onecore_maintenance_extension/models/services/onecore_flag_sync_service.py` — the whole sync
- Modify `onecore_maintenance_extension/models/services/__init__.py` — export
- Create `onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py`
- Rewrite `onecore_maintenance_extension/tests/models/test_maintenance_pest_control.py`
- Modify `onecore_maintenance_extension/data/ir_cron.xml` — two cron records
- Modify `onecore_maintenance_extension/views/maintenance_views.xml` — kanban field, list column, search filter
- Modify `onecore_maintenance_extension/static/src/views/maintenance_request_item.xml` — kanban badge
- Modify `onecore_maintenance_extension/views/mobile_view.xml` — mobile field + badge

The sync lives in one service file rather than being split per flag: the two flags share the open-request query, the changed-only write discipline and the `is_configured` guard, and the file stays well under 250 lines.

---

## Task 1: onecore — lean rental-ids endpoint (property service)

**Repo:** onecore worktree.

**Files:**
- Modify: `services/property/src/types/residence.ts` (after `searchRentalBlocksQueryParamsSchema`, ~line 279)
- Modify: `services/property/src/adapters/residence-adapter.ts` (after `searchRentalBlocks`, ~line 1630)
- Modify: `services/property/src/routes/residences.ts` (after the `rental-blocks/all` route, ~line 1110)
- Test: `services/property/src/tests/rental-blocks-rental-ids.test.ts`

**Interfaces:**
- Consumes: `buildRentalBlockWhereClause(options)` and `prisma` — both already in `residence-adapter.ts`; `arrayQueryParam` and `booleanStringSchema` — both already in `types/residence.ts`
- Produces: `getRentalIdsWithBlock(options: RentalIdsWithBlockOptions): Promise<string[]>`, `rentalIdsWithBlockQueryParamsSchema`, and the route `GET /residences/rental-blocks/rental-ids` returning `{ content: string[] }`

- [ ] **Step 1: Write the failing test**

Create `services/property/src/tests/rental-blocks-rental-ids.test.ts`:

```ts
import request from 'supertest'

import app from '../app'
import * as residenceAdapter from '../adapters/residence-adapter'

afterEach(() => {
  jest.restoreAllMocks()
})

describe('GET /residences/rental-blocks/rental-ids', () => {
  it('returns the rental ids the adapter resolves', async () => {
    const spy = jest
      .spyOn(residenceAdapter, 'getRentalIdsWithBlock')
      .mockResolvedValue(['705-022-04-0201', '705-022-04-0202'])

    const res = await request(app.callback()).get(
      '/residences/rental-blocks/rental-ids?blockReason=SKADEDJUR&active=true'
    )

    expect(res.status).toBe(200)
    expect(res.body.content).toEqual([
      '705-022-04-0201',
      '705-022-04-0202',
    ])
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ blockReason: ['SKADEDJUR'], active: true })
    )
  })

  it('returns an empty list when nothing is blocked', async () => {
    jest
      .spyOn(residenceAdapter, 'getRentalIdsWithBlock')
      .mockResolvedValue([])

    const res = await request(app.callback()).get(
      '/residences/rental-blocks/rental-ids?blockReason=SKADEDJUR&active=true'
    )

    expect(res.status).toBe(200)
    expect(res.body.content).toEqual([])
  })

  it('works with no filters at all', async () => {
    const spy = jest
      .spyOn(residenceAdapter, 'getRentalIdsWithBlock')
      .mockResolvedValue(['705-022-04-0201'])

    const res = await request(app.callback()).get(
      '/residences/rental-blocks/rental-ids'
    )

    expect(res.status).toBe(200)
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ blockReason: undefined, active: undefined })
    )
  })

  it('returns 500 when the adapter throws', async () => {
    jest
      .spyOn(residenceAdapter, 'getRentalIdsWithBlock')
      .mockRejectedValue(new Error('boom'))

    const res = await request(app.callback()).get(
      '/residences/rental-blocks/rental-ids?blockReason=SKADEDJUR'
    )

    expect(res.status).toBe(500)
    expect(res.body.reason).toBe('boom')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/property && npx jest --config jest.config.js rental-blocks-rental-ids`
Expected: FAIL — `getRentalIdsWithBlock` does not exist on the adapter module, and the route 404s.

- [ ] **Step 3: Add the query-param schema**

In `services/property/src/types/residence.ts`, immediately after `searchRentalBlocksQueryParamsSchema` (~line 279):

```ts
export const rentalIdsWithBlockQueryParamsSchema = z.object({
  blockReason: arrayQueryParam,
  active: booleanStringSchema.optional(),
})

export type RentalIdsWithBlockQueryParams = z.infer<
  typeof rentalIdsWithBlockQueryParamsSchema
>
```

- [ ] **Step 4: Add the adapter function**

In `services/property/src/adapters/residence-adapter.ts`, after `searchRentalBlocks` ends (~line 1630):

```ts
export type RentalIdsWithBlockOptions = Pick<
  SearchRentalBlocksOptions,
  'blockReason' | 'active'
>

/**
 * Distinct rental ids currently carrying a matching rental block.
 *
 * Deliberately lean. Consumers that only need "is this object blocked" —
 * Odoo's kanban badges (MIM-1959) — must not pay for the COUNT, the rent
 * lookup and the district enrichment that searchRentalBlocks does for the
 * spärrlista UI. Reuses buildRentalBlockWhereClause so the filter semantics
 * cannot drift from the list, including its base "rentalId is not empty"
 * condition.
 */
export const getRentalIdsWithBlock = async (
  options: RentalIdsWithBlockOptions
): Promise<string[]> => {
  try {
    const rows = await prisma.rentalBlock.findMany({
      where: buildRentalBlockWhereClause(options),
      select: {
        propertyStructure: {
          select: {
            rentalId: true,
          },
        },
      },
    })

    return [
      ...new Set(
        rows
          .map((row) => row.propertyStructure?.rentalId?.trim())
          .filter((rentalId): rentalId is string => !!rentalId)
      ),
    ]
  } catch (err) {
    logger.error({ err }, 'residence-adapter.getRentalIdsWithBlock')
    throw err
  }
}
```

- [ ] **Step 5: Add the route**

In `services/property/src/routes/residences.ts`, after the `rental-blocks/all` route closes (~line 1110). Import `getRentalIdsWithBlock` from the adapter and `rentalIdsWithBlockQueryParamsSchema` from the types module alongside the existing imports.

```ts
  /**
   * @swagger
   * /residences/rental-blocks/rental-ids:
   *   get:
   *     summary: Rental ids carrying a matching rental block
   *     description: >
   *       Lean companion to /residences/rental-blocks/search. Returns only the
   *       distinct rental ids, with no pagination, rent data or district
   *       enrichment - for consumers that need to answer "is this object
   *       blocked" in bulk.
   *     tags:
   *       - Residences
   *     parameters:
   *       - in: query
   *         name: blockReason
   *         schema:
   *           type: array
   *           items:
   *             type: string
   *         style: form
   *         explode: true
   *         description: Filter by block reason caption (supports multiple values)
   *       - in: query
   *         name: active
   *         schema:
   *           type: boolean
   *         description: >
   *           true = not yet ended (toDate >= today or null), false = already
   *           ended (toDate < today). If omitted, all blocks.
   *     responses:
   *       200:
   *         description: Successfully retrieved rental ids
   *         content:
   *           application/json:
   *             schema:
   *               type: object
   *               properties:
   *                 content:
   *                   type: array
   *                   items:
   *                     type: string
   *       500:
   *         description: Internal server error
   */
  router.get(
    '(.*)/residences/rental-blocks/rental-ids',
    parseRequest({ query: rentalIdsWithBlockQueryParamsSchema }),
    async (ctx) => {
      const metadata = generateRouteMetadata(ctx)

      try {
        const rentalIds = await getRentalIdsWithBlock(ctx.request.parsedQuery)

        ctx.status = 200
        ctx.body = { content: rentalIds, ...metadata }
      } catch (err) {
        logger.error(err, 'Error fetching rental ids with block')
        ctx.status = 500
        const errorMessage =
          err instanceof Error ? err.message : 'unknown error'
        ctx.body = { reason: errorMessage, ...metadata }
      }
    }
  )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd services/property && npx jest --config jest.config.js rental-blocks-rental-ids`
Expected: PASS, 4 tests.

- [ ] **Step 7: Lint and format**

Run: `cd services/property && npx prettier --write src/routes/residences.ts src/adapters/residence-adapter.ts src/types/residence.ts src/tests/rental-blocks-rental-ids.test.ts && npx eslint src/`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add services/property/src/types/residence.ts \
        services/property/src/adapters/residence-adapter.ts \
        services/property/src/routes/residences.ts \
        services/property/src/tests/rental-blocks-rental-ids.test.ts
git commit -m "feat(property): lean rental-ids endpoint for rental blocks (MIM-1959)"
```

---

## Task 2: onecore — proxy the endpoint through core

**Repo:** onecore worktree.

**Files:**
- Modify: `core/src/adapters/property-base-adapter/index.ts` (after `searchRentalBlocks`, ~line 927)
- Modify: `core/src/services/property-base-service/index.ts` (after the `rental-blocks/all` route, ~line 1610)
- Test: `core/src/services/property-base-service/tests/rental-blocks-rental-ids.test.ts`

**Interfaces:**
- Consumes: Task 1's `GET /residences/rental-blocks/rental-ids` on the property service
- Produces: `getRentalIdsWithBlock(queryParams): Promise<AdapterResult<string[], 'unknown'>>` on the core property-base adapter, and the core route `GET /residences/rental-blocks/rental-ids` returning `{ content: string[] }`

Uses raw `axios` against `config.propertyBaseService.url`, matching `searchRentalBlocks` (`index.ts:914`), rather than the generated `client()`. That deliberately avoids a `pnpm generate-types:property-base` step, which needs the property service running locally.

- [ ] **Step 1: Write the failing test**

Create `core/src/services/property-base-service/tests/rental-blocks-rental-ids.test.ts`:

```ts
import request from 'supertest'
import Koa from 'koa'
import KoaRouter from '@koa/router'
import bodyParser from 'koa-bodyparser'

import { routes as propertyBaseRoutes } from '../index'
import * as propertyBaseAdapter from '../../../adapters/property-base-adapter'

function app() {
  const a = new Koa()
  const r = new KoaRouter()
  a.use(bodyParser())
  propertyBaseRoutes(r)
  a.use(r.routes())
  return a
}

beforeEach(jest.resetAllMocks)

describe('GET /residences/rental-blocks/rental-ids', () => {
  it('passes the query through and returns the ids', async () => {
    const spy = jest
      .spyOn(propertyBaseAdapter, 'getRentalIdsWithBlock')
      .mockResolvedValue({ ok: true, data: ['705-022-04-0201'] })

    const res = await request(app().callback()).get(
      '/residences/rental-blocks/rental-ids?blockReason=SKADEDJUR&active=true'
    )

    expect(res.status).toBe(200)
    expect(res.body.content).toEqual(['705-022-04-0201'])
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ blockReason: 'SKADEDJUR', active: 'true' })
    )
  })

  it('returns 500 when the adapter fails', async () => {
    jest
      .spyOn(propertyBaseAdapter, 'getRentalIdsWithBlock')
      .mockResolvedValue({ ok: false, err: 'unknown' })

    const res = await request(app().callback()).get(
      '/residences/rental-blocks/rental-ids?blockReason=SKADEDJUR'
    )

    expect(res.status).toBe(500)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && npx jest rental-blocks-rental-ids`
Expected: FAIL — `getRentalIdsWithBlock` is not exported by the adapter.

- [ ] **Step 3: Add the core adapter function**

In `core/src/adapters/property-base-adapter/index.ts`, after `searchRentalBlocks` ends (~line 927):

```ts
export async function getRentalIdsWithBlock(
  queryParams: QueryParams
): Promise<AdapterResult<string[], 'unknown'>> {
  try {
    const params = new URLSearchParams()
    Object.entries(queryParams).forEach(([key, value]) => {
      if (value === undefined) return
      if (Array.isArray(value)) {
        value.forEach((v) => params.append(key, String(v)))
      } else {
        params.append(key, String(value))
      }
    })

    const response = await axios.get(
      `${config.propertyBaseService.url}/residences/rental-blocks/rental-ids`,
      { params }
    )

    return { ok: true, data: response.data.content as string[] }
  } catch (err) {
    logger.error({ err }, 'property-base-adapter.getRentalIdsWithBlock')
    return { ok: false, err: 'unknown' }
  }
}
```

- [ ] **Step 4: Add the core route**

In `core/src/services/property-base-service/index.ts`, after the `rental-blocks/all` route closes (~line 1610):

```ts
  /**
   * @swagger
   * /residences/rental-blocks/rental-ids:
   *   get:
   *     summary: Rental ids carrying a matching rental block
   *     description: >
   *       Lean bulk lookup - distinct rental ids only, no pagination or
   *       enrichment. Used by Odoo to render the "Spärr skadedjur" badge on
   *       every kanban card from a single call.
   *     tags:
   *       - Property base Service
   *     parameters:
   *       - in: query
   *         name: blockReason
   *         schema:
   *           type: array
   *           items:
   *             type: string
   *         style: form
   *         explode: true
   *       - in: query
   *         name: active
   *         schema:
   *           type: boolean
   *     responses:
   *       200:
   *         description: Successfully retrieved rental ids
   *       500:
   *         description: Internal server error
   */
  router.get('(.*)/residences/rental-blocks/rental-ids', async (ctx) => {
    const metadata = generateRouteMetadata(ctx)

    try {
      const result = await propertyBaseAdapter.getRentalIdsWithBlock(ctx.query)

      if (!result.ok) {
        logger.error({ err: result.err, metadata }, 'Internal server error')
        ctx.status = 500
        ctx.body = { error: 'Internal server error', ...metadata }
        return
      }

      ctx.status = 200
      ctx.body = { content: result.data, ...metadata }
    } catch (error) {
      logger.error({ error, metadata }, 'Internal server error')
      ctx.status = 500
      ctx.body = { error: 'Internal server error', ...metadata }
    }
  })
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd core && npx jest rental-blocks-rental-ids`
Expected: PASS, 2 tests.

- [ ] **Step 6: Run the full core suite for regressions**

Run: `cd core && npx jest property-base`
Expected: PASS — the new route must not shadow `rental-blocks/by-rental-id/:rentalId` or `rental-blocks/all`.

- [ ] **Step 7: Lint and format**

Run: `cd core && npx prettier --write src/adapters/property-base-adapter/index.ts src/services/property-base-service/index.ts src/services/property-base-service/tests/rental-blocks-rental-ids.test.ts && npx eslint src/`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add core/src/adapters/property-base-adapter/index.ts \
        core/src/services/property-base-service/index.ts \
        core/src/services/property-base-service/tests/rental-blocks-rental-ids.test.ts
git commit -m "feat(core): proxy lean rental-ids endpoint for rental blocks (MIM-1959)"
```

---

## Task 3: Odoo — CoreApi fetch methods

**Repo:** onecore-odoo worktree. Everything from here on is onecore-odoo.

**Files:**
- Modify: `onecore_api/core_api.py` (after `fetch_residence`, ~line 299)
- Test: `onecore_api/tests/test_core_api.py`

**Interfaces:**
- Consumes: Task 2's core route `GET /residences/rental-blocks/rental-ids`; the pre-existing `GET /residences/block-reasons` and `GET /v1/contacts/batch`
- Produces, all on `CoreApi`:
  - `fetch_pest_blocked_rental_ids(block_reason: str = "SKADEDJUR", **kwargs) -> list[str]`
  - `fetch_block_reason_captions(**kwargs) -> list[str]`
  - `fetch_contacts_batch(contact_codes: list[str], **kwargs) -> list[dict]`

- [ ] **Step 1: Write the failing test**

Append to `onecore_api/tests/test_core_api.py`:

```python
class TestFetchPestBlockedRentalIds:
    """GET /residences/rental-blocks/rental-ids — the bulk pest lookup."""

    def test_builds_url_with_reason_and_active(self, api):
        with patch.object(CoreApi, "_get_json") as get_json:
            get_json.return_value = ["705-022-04-0201"]
            result = api.fetch_pest_blocked_rental_ids(timeout=15)

        assert result == ["705-022-04-0201"]
        get_json.assert_called_once_with(
            "/residences/rental-blocks/rental-ids?blockReason=SKADEDJUR&active=true",
            timeout=15,
        )

    def test_reason_is_url_encoded(self, api):
        with patch.object(CoreApi, "_get_json") as get_json:
            get_json.return_value = []
            api.fetch_pest_blocked_rental_ids(block_reason="A B")

        assert "blockReason=A+B" in get_json.call_args[0][0]


class TestFetchBlockReasonCaptions:
    """GET /residences/block-reasons — guards against a caption rename."""

    def test_returns_captions(self, api):
        with patch.object(CoreApi, "_get_json") as get_json:
            get_json.return_value = [
                {"id": "1", "caption": "SKADEDJUR"},
                {"id": "2", "caption": "RENOVERING"},
            ]
            assert api.fetch_block_reason_captions() == [
                "SKADEDJUR",
                "RENOVERING",
            ]

    def test_skips_entries_without_caption(self, api):
        with patch.object(CoreApi, "_get_json") as get_json:
            get_json.return_value = [{"id": "1"}, {"id": "2", "caption": "X"}]
            assert api.fetch_block_reason_captions() == ["X"]

    def test_none_content_is_empty(self, api):
        with patch.object(CoreApi, "_get_json") as get_json:
            get_json.return_value = None
            assert api.fetch_block_reason_captions() == []


class TestFetchContactsBatch:
    """GET /v1/contacts/batch — repeated ?code= params."""

    def test_repeats_the_code_param(self, api):
        with patch.object(CoreApi, "_get_json") as get_json:
            get_json.return_value = [{"contactCode": "P1"}]
            result = api.fetch_contacts_batch(["P1", "P2"], timeout=15)

        assert result == [{"contactCode": "P1"}]
        get_json.assert_called_once_with(
            "/v1/contacts/batch?code=P1&code=P2", timeout=15
        )

    def test_empty_codes_does_not_call_onecore(self, api):
        with patch.object(CoreApi, "_get_json") as get_json:
            assert api.fetch_contacts_batch([]) == []
            get_json.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest onecore_api/tests/test_core_api.py -k "PestBlocked or BlockReasonCaptions or ContactsBatch" -v`
Expected: FAIL with `AttributeError: 'CoreApi' object has no attribute 'fetch_pest_blocked_rental_ids'`.

- [ ] **Step 3: Add the three methods**

In `onecore_api/core_api.py`, immediately after `fetch_residence` (~line 299):

```python
    def fetch_pest_blocked_rental_ids(self, block_reason="SKADEDJUR", **kwargs):
        """Every rental id carrying an active ``block_reason`` block.

        One call for the whole estate. The kanban badge must never cost an API
        call per card (MIM-1869), so the caller snapshots this set instead of
        asking per request.
        """
        query = urllib.parse.urlencode(
            {"blockReason": block_reason, "active": "true"}
        )
        return self._get_json(
            f"/residences/rental-blocks/rental-ids?{query}", **kwargs
        )

    def fetch_block_reason_captions(self, **kwargs):
        """Known block-reason captions.

        The pest lookup filters on a caption, so a rename in Xpand would return
        an empty set that is indistinguishable from "nothing is blocked".
        Callers check this list before believing an empty result.
        """
        content = self._get_json("/residences/block-reasons", **kwargs) or []
        return [item.get("caption") for item in content if item.get("caption")]

    def fetch_contacts_batch(self, contact_codes, **kwargs):
        """Lean batch contact lookup by contact code.

        Returns the ``content`` list; codes OneCore does not know are simply
        absent from it. Base contact columns only - no phone/email/address
        joins are requested.
        """
        if not contact_codes:
            return []
        query = urllib.parse.urlencode([("code", code) for code in contact_codes])
        return self._get_json(f"/v1/contacts/batch?{query}", **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest onecore_api/tests/test_core_api.py -k "PestBlocked or BlockReasonCaptions or ContactsBatch" -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Run the whole CoreApi suite**

Run: `pytest onecore_api/tests/test_core_api.py`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add onecore_api/core_api.py onecore_api/tests/test_core_api.py
git commit -m "feat(api): batch fetches for pest blocks, block reasons and contacts (MIM-1959)"
```

---

## Task 4: Odoo — make `requires_pest_control` a stored field

**Files:**
- Modify: `onecore_maintenance_extension/models/maintenance.py:5` (drop `import time`), `:44-47` (drop the cache), `:205-209` (field), `:414-451` (drop the compute)
- Test: `onecore_maintenance_extension/tests/models/test_maintenance_pest_control.py` (rewrite)

**Interfaces:**
- Produces: `maintenance.request.requires_pest_control` as a plain stored Boolean, default `False`, written only by `OneCoreFlagSyncService` (Tasks 5 and 7)

After this task the form badge reads `False` for every case until Task 5 and Task 8 land. That is expected inside the feature branch.

- [ ] **Step 1: Rewrite the test file**

Replace the entire contents of `onecore_maintenance_extension/tests/models/test_maintenance_pest_control.py`:

```python
"""The "Spärr skadedjur" flag is a stored snapshot, not a computed value.

It used to be computed per record with a live OneCore call, which is why it
could only ever appear on the form (MIM-1959). It is now written by
OneCoreFlagSyncService - on the create path and by the cron - so the kanban can
render it without one API call per card. These tests pin the field's shape; the
sync behaviour lives in tests/models/services/test_onecore_flag_sync_service.py.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..utils.test_utils import create_maintenance_request, create_rental_property


@tagged("onecore")
class TestRequiresPestControlField(TransactionCase):
    def setUp(self):
        super().setUp()
        self.rental_property = create_rental_property(
            self.env, rental_property_id="705-022-04-0201"
        )
        self.request = create_maintenance_request(
            self.env,
            space_caption="Lägenhet",
            rental_property_id=self.rental_property.id,
        )

    def test_defaults_to_false(self):
        self.assertFalse(self.request.requires_pest_control)

    def test_is_stored(self):
        field = self.env["maintenance.request"]._fields["requires_pest_control"]
        self.assertTrue(field.store)
        self.assertFalse(field.compute)

    def test_survives_a_reread(self):
        """A stored value must not be recomputed away on the next read."""
        self.request.sudo().write({"requires_pest_control": True})
        self.request.invalidate_recordset(["requires_pest_control"])
        self.assertTrue(self.request.requires_pest_control)

    def test_is_searchable(self):
        """Storing it is what lets the list view filter and group on it."""
        self.request.sudo().write({"requires_pest_control": True})
        found = self.env["maintenance.request"].search(
            [("requires_pest_control", "=", True), ("id", "=", self.request.id)]
        )
        self.assertEqual(found, self.request)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./run_tests.sh`
Expected: FAIL — `test_is_stored` fails because the field still declares `compute="_compute_requires_pest_control"`, and `test_survives_a_reread` fails because the compute overwrites the written value.

- [ ] **Step 3: Delete the per-worker cache**

In `onecore_maintenance_extension/models/maintenance.py`, delete lines 44-47 entirely:

```python
# Per-worker cache so the pest control badge doesn't trigger a OneCore call on
# every form read (web_save re-reads included). Worst-case staleness = TTL.
PEST_CONTROL_CACHE_TTL = 300  # seconds
_pest_control_cache = {}  # rental_id -> (expires_at_monotonic, bool)
```

Then delete `import time` from line 5. Verify nothing else uses it:

Run: `grep -n "time\." onecore_maintenance_extension/models/maintenance.py`
Expected: only `fields.Datetime` hits — no bare `time.` calls remain.

- [ ] **Step 4: Replace the field definition**

At `models/maintenance.py:205-209`, replace:

```python
    # Form-view only. Adding this to tree/kanban would fire one API call per row.
    requires_pest_control = fields.Boolean(
        string="Spärr skadedjur",
        compute="_compute_requires_pest_control",
        store=False,
    )
```

with:

```python
    # Stored snapshot written only by OneCoreFlagSyncService (create path +
    # cron). Computing it per record would fire one OneCore call per kanban
    # card, which is why it used to be form-only (MIM-1959).
    requires_pest_control = fields.Boolean(
        string="Spärr skadedjur",
        store=True,
        readonly=True,
        default=False,
    )
```

- [ ] **Step 5: Delete the compute method**

Delete the whole `_compute_requires_pest_control` method (`models/maintenance.py:413-451`), including its `@api.depends("rental_property_id", "rental_property_option_id")` decorator.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./run_tests.sh`
Expected: PASS. `test_maintenance_pest_control.py` contributes 4 passing tests and nothing else regresses.

- [ ] **Step 7: Format and commit**

```bash
black onecore_maintenance_extension/models/maintenance.py \
      onecore_maintenance_extension/tests/models/test_maintenance_pest_control.py
git add onecore_maintenance_extension/models/maintenance.py \
        onecore_maintenance_extension/tests/models/test_maintenance_pest_control.py
git commit -m "refactor(mim-1959): store requires_pest_control instead of computing it"
```

---

## Task 5: Odoo — the pest-control sync service

**Files:**
- Create: `onecore_maintenance_extension/models/services/onecore_flag_sync_service.py`
- Modify: `onecore_maintenance_extension/models/services/__init__.py`
- Test: `onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py`

**Interfaces:**
- Consumes: Task 3's `CoreApi.fetch_pest_blocked_rental_ids`, `CoreApi.fetch_block_reason_captions`; Task 4's stored `requires_pest_control`
- Produces, on `OneCoreFlagSyncService(env)`:
  - `is_configured() -> bool`
  - `get_rental_id(request) -> str | False` (staticmethod)
  - `open_requests() -> recordset`
  - `fetch_pest_blocked_rental_ids(api=None) -> set[str]` — **raises** on failure
  - `sync_pest_control(api=None) -> int` (number of requests changed)
  - module constants `PEST_BLOCK_REASON`, `LOOKUP_TIMEOUT`, `PEST_SET_CACHE_TTL`, `_pest_set_cache`

- [ ] **Step 1: Write the failing test**

Create `onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py`:

```python
"""Tests for OneCoreFlagSyncService (MIM-1959) — the batch refresh of the two
OneCore safety flags behind the kanban badges.

OneCore is always mocked (patch CoreApi); ``onecore_base_url`` is only set in
tests that expect a call, because the service refuses to construct the client
without it.
"""
import time
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...utils.test_utils import (
    create_facility,
    create_maintenance_request,
    create_parking_space,
    create_rental_property,
)
from ....models.services import onecore_flag_sync_service as sync_module
from ....models.services.onecore_flag_sync_service import OneCoreFlagSyncService

CORE_API_PATH = "odoo.addons.onecore_api.core_api.CoreApi"

BLOCKED_RENTAL_ID = "705-022-04-0201"
FREE_RENTAL_ID = "705-022-04-0202"


class FlagSyncTestMixin:
    def setUp(self):
        super().setUp()
        sync_module._pest_set_cache.clear()
        self.service = OneCoreFlagSyncService(self.env)

    def _configure_onecore(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "onecore_base_url", "https://core.test"
        )

    def _apartment_request(self, rental_id=BLOCKED_RENTAL_ID, **kwargs):
        rental_property = create_rental_property(
            self.env, rental_property_id=rental_id
        )
        request = create_maintenance_request(
            self.env,
            space_caption="Lägenhet",
            rental_property_id=rental_property.id,
            **kwargs,
        )
        return self.env["maintenance.request"].browse(request.id)

    def _mock_api(self, MockApi, blocked=None, captions=None):
        MockApi.return_value.fetch_block_reason_captions.return_value = (
            captions if captions is not None else ["SKADEDJUR", "RENOVERING"]
        )
        MockApi.return_value.fetch_pest_blocked_rental_ids.return_value = (
            blocked if blocked is not None else []
        )
        return MockApi.return_value


@tagged("onecore")
class TestRentalIdResolution(FlagSyncTestMixin, TransactionCase):
    def test_rental_id_from_rental_property(self):
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        self.assertEqual(
            self.service.get_rental_id(request), BLOCKED_RENTAL_ID
        )

    def test_rental_id_from_parking_space(self):
        request = create_maintenance_request(self.env, space_caption="Bilplats")
        parking = create_parking_space(
            self.env,
            maintenance_request_id=request.id,
            rental_property_id="303-001-01-0001",
        )
        request.parking_space_id = parking.id
        self.assertEqual(self.service.get_rental_id(request), "303-001-01-0001")

    def test_rental_id_from_facility(self):
        request = create_maintenance_request(self.env, space_caption="Lokal")
        facility = create_facility(
            self.env,
            maintenance_request_id=request.id,
            rental_property_id="404-001-01-0001",
        )
        request.facility_id = facility.id
        self.assertEqual(self.service.get_rental_id(request), "404-001-01-0001")

    def test_no_rental_object_resolves_to_false(self):
        request = create_maintenance_request(self.env, space_caption="Tvättstuga")
        self.assertFalse(self.service.get_rental_id(request))


@tagged("onecore")
class TestSyncPestControl(FlagSyncTestMixin, TransactionCase):
    def test_blocked_rental_id_sets_the_flag(self):
        self._configure_onecore()
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertTrue(request.requires_pest_control)

    def test_lifted_block_clears_the_flag(self):
        self._configure_onecore()
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        request.sudo().write({"requires_pest_control": True})

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[])
            self.service.sync_pest_control()

        self.assertFalse(request.requires_pest_control)

    def test_unrelated_rental_id_is_untouched(self):
        self._configure_onecore()
        request = self._apartment_request(rental_id=FREE_RENTAL_ID)

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertFalse(request.requires_pest_control)

    def test_parking_space_request_gets_the_flag(self):
        """Regression: the old compute only ever called fetch_residence, so
        parking and facility cases silently resolved to False."""
        self._configure_onecore()
        request = create_maintenance_request(self.env, space_caption="Bilplats")
        parking = create_parking_space(
            self.env,
            maintenance_request_id=request.id,
            rental_property_id="303-001-01-0001",
        )
        request.parking_space_id = parking.id

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=["303-001-01-0001"])
            self.service.sync_pest_control()

        self.assertTrue(request.requires_pest_control)

    def test_request_without_a_rental_object_is_cleared(self):
        """A property- or building-level case has nothing to block. If it holds
        a stale True it must be cleared, not merely skipped."""
        self._configure_onecore()
        request = create_maintenance_request(self.env, space_caption="Tvättstuga")
        request.sudo().write({"requires_pest_control": True})

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertFalse(request.requires_pest_control)

    def test_fetch_failure_writes_nothing(self):
        self._configure_onecore()
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        request.sudo().write({"requires_pest_control": True})

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_block_reason_captions.return_value = [
                "SKADEDJUR"
            ]
            MockApi.return_value.fetch_pest_blocked_rental_ids.side_effect = (
                Exception("boom")
            )
            changed = self.service.sync_pest_control()

        self.assertEqual(changed, 0)
        self.assertTrue(request.requires_pest_control)

    def test_missing_caption_aborts_without_clearing(self):
        """A rename in Xpand returns an empty set that looks exactly like
        "nothing is blocked". Refuse the run rather than clear every badge."""
        self._configure_onecore()
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        request.sudo().write({"requires_pest_control": True})

        with patch(CORE_API_PATH) as MockApi:
            api = self._mock_api(MockApi, blocked=[], captions=["RENOVERING"])
            changed = self.service.sync_pest_control()

        self.assertEqual(changed, 0)
        self.assertTrue(request.requires_pest_control)
        api.fetch_pest_blocked_rental_ids.assert_not_called()

    def test_closed_requests_are_excluded(self):
        self._configure_onecore()
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        request.sudo().write({"closed_date": fields.Datetime.now()})

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertFalse(request.requires_pest_control)

    def test_archived_requests_are_excluded(self):
        self._configure_onecore()
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        request.sudo().write({"archive": True})

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertFalse(request.requires_pest_control)

    def test_unchanged_run_writes_nothing(self):
        """Steady state must cost zero UPDATEs — that is what makes a
        15-minute cadence affordable."""
        self._configure_onecore()
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.assertEqual(self.service.sync_pest_control(), 1)
            self.assertEqual(self.service.sync_pest_control(), 0)

        self.assertTrue(request.requires_pest_control)

    def test_unconfigured_onecore_is_a_no_op(self):
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)

        with patch(CORE_API_PATH) as MockApi:
            changed = self.service.sync_pest_control()

        self.assertEqual(changed, 0)
        self.assertFalse(request.requires_pest_control)
        MockApi.assert_not_called()

    def test_flag_change_posts_no_chatter(self):
        """Spec decision 3: the badge changes silently."""
        self._configure_onecore()
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        before = len(request.message_ids)

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertEqual(len(request.message_ids), before)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh`
Expected: FAIL — `ModuleNotFoundError` / `ImportError` for `onecore_flag_sync_service`.

- [ ] **Step 3: Create the service**

Create `onecore_maintenance_extension/models/services/onecore_flag_sync_service.py`:

```python
"""OneCore safety flags on maintenance requests: viktig kundinfo + spärr skadedjur.

Both badges have to render in the kanban overview (MIM-1959), so neither may be
computed on read - that would fire one OneCore call per card. Instead the flags
are snapshotted on the request (and on its tenant) by the write path and two
crons, the same shape as ManagementAreaService (MIM-1869).

Only records whose value actually changed are written. A run where nothing moved
issues no UPDATE at all, which is what keeps a 15-minute cadence cheap - and is
why there is no per-record "synced at" stamp: writing one would touch every open
request every run.
"""

import logging
import time

_logger = logging.getLogger(__name__)

# Seconds. A slow OneCore must not stall a cron run or a case creation.
LOOKUP_TIMEOUT = 15

# The caption Xpand uses. Matches the comparison in property-tree's residence
# view (ResidenceBasicInfo.tsx) - the block reason is a caption everywhere.
PEST_BLOCK_REASON = "SKADEDJUR"

# Per-worker cache of the blocked-rental-id set so a burst of case creations
# shares one OneCore call. Only the create path reads it; the cron always
# fetches fresh. Keyed on database: onecore_base_url is a per-database setting,
# so a worker serving several databases must not hand a staging answer to a
# production request.
PEST_SET_CACHE_TTL = 300  # seconds
_pest_set_cache = {}  # dbname -> (expires_at_monotonic, frozenset)


class OneCoreFlagSyncService:
    """Batch refresh of the two OneCore flags the kanban badges read."""

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Shared
    # ------------------------------------------------------------------
    def is_configured(self):
        """Is OneCore reachable at all? Checked BEFORE constructing CoreApi:
        its __init__ POSTs for a token when none is persisted."""
        return bool(
            self.env["ir.config_parameter"].sudo().get_param("onecore_base_url")
        )

    def _api(self, api=None):
        return api or self.env["maintenance.request"].get_core_api()

    @staticmethod
    def get_rental_id(request):
        """OneCore's rentalId for the request's object, whatever its kind.

        Property- and building-level requests have no rental object and return
        False - they can never carry a rental block.
        """
        return (
            request.rental_property_id.rental_property_id
            or request.parking_space_id.rental_property_id
            or request.facility_id.rental_property_id
            or False
        )

    def open_requests(self):
        """Requests the badges are still shown on. Closed ones keep their last
        known value: the badge is about the object's current state, which stops
        being interesting once the case is done."""
        return (
            self.env["maintenance.request"]
            .sudo()
            .search([("closed_date", "=", False), ("archive", "=", False)])
        )

    @staticmethod
    def _apply(records, field, to_set, to_clear):
        """Two grouped writes, and none at all when nothing changed.

        skip_change_tracking: a flag flip must not post a chatter note
        (MIM-1959 decision 3) and one message_post per record would be slow.
        """
        model = records.browse([])
        if to_set:
            model.browse(to_set).with_context(skip_change_tracking=True).write(
                {field: True}
            )
        if to_clear:
            model.browse(to_clear).with_context(skip_change_tracking=True).write(
                {field: False}
            )
        return len(to_set) + len(to_clear)

    # ------------------------------------------------------------------
    # Spärr skadedjur
    # ------------------------------------------------------------------
    def fetch_pest_blocked_rental_ids(self, api=None):
        """Every rental id with an active SKADEDJUR block, as a set.

        Raises on failure and on a missing SKADEDJUR caption. An empty set is
        indistinguishable from "nothing is blocked", so a partial or
        accidentally-empty answer would clear the badge on genuinely blocked
        objects. All-or-nothing, like ManagementAreaService.build_property_map.
        """
        api = self._api(api)
        captions = api.fetch_block_reason_captions(timeout=LOOKUP_TIMEOUT)
        if PEST_BLOCK_REASON not in captions:
            raise ValueError(
                "OneCore does not know the block reason %s (got %s); refusing "
                "to clear the pest flag on every request"
                % (PEST_BLOCK_REASON, captions)
            )
        rental_ids = api.fetch_pest_blocked_rental_ids(
            block_reason=PEST_BLOCK_REASON, timeout=LOOKUP_TIMEOUT
        )
        return {rental_id for rental_id in (rental_ids or []) if rental_id}

    def sync_pest_control(self, api=None):
        """Refresh requires_pest_control on every open request.

        Returns the number of requests whose value changed, or 0 when OneCore
        could not be asked - in which case nothing is written and the last
        known values stand.
        """
        if not self.is_configured():
            _logger.info(
                "Pest-control sync skipped: onecore_base_url is not set"
            )
            return 0

        try:
            blocked = self.fetch_pest_blocked_rental_ids(api=api)
        except Exception as err:  # network, auth, caption rename
            _logger.warning("Pest-control sync skipped: %s", err)
            return 0

        requests = self.open_requests()
        to_set, to_clear = [], []
        for record in requests:
            rental_id = self.get_rental_id(record)
            desired = bool(rental_id) and rental_id in blocked
            if desired and not record.requires_pest_control:
                to_set.append(record.id)
            elif not desired and record.requires_pest_control:
                to_clear.append(record.id)

        changed = self._apply(
            requests, "requires_pest_control", to_set, to_clear
        )
        _logger.info(
            "Pest-control sync: %s blocked rental ids, %s open requests, "
            "%s set, %s cleared",
            len(blocked),
            len(requests),
            len(to_set),
            len(to_clear),
        )
        return changed
```

- [ ] **Step 4: Export the service**

Append to `onecore_maintenance_extension/models/services/__init__.py`:

```python
from .onecore_flag_sync_service import OneCoreFlagSyncService
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./run_tests.sh`
Expected: PASS — `TestRentalIdResolution` (4 tests) and `TestSyncPestControl` (12 tests) all green.

- [ ] **Step 6: Format and commit**

```bash
black onecore_maintenance_extension/models/services/onecore_flag_sync_service.py \
      onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py
git add onecore_maintenance_extension/models/services/onecore_flag_sync_service.py \
        onecore_maintenance_extension/models/services/__init__.py \
        onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py
git commit -m "feat(mim-1959): batch-sync the skadedjur flag onto open requests"
```

---

## Task 6: Odoo — the viktig kundinfo sync

**Files:**
- Modify: `onecore_maintenance_extension/models/services/onecore_flag_sync_service.py`
- Test: `onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py`

**Interfaces:**
- Consumes: Task 3's `CoreApi.fetch_contacts_batch`; Task 5's `open_requests()` and `_apply()`
- Produces, on `OneCoreFlagSyncService`:
  - `fetch_special_attention(contact_codes, api=None) -> dict[str, bool]`
  - `sync_special_attention(api=None) -> int`
  - module constant `CONTACT_BATCH_SIZE`

Unlike the pest set, a missing answer here is per-code and harmless: an absent code simply keeps its stored value. So a failing chunk is logged and skipped rather than aborting the run.

- [ ] **Step 1: Write the failing test**

Append to `onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py`:

```python
def _contact(code, special_attention):
    """Shape of one item in GET /v1/contacts/batch ``content``."""
    return {
        "contactCode": code,
        "communication": {
            "phoneNumbers": [],
            "emailAddresses": [],
            "specialAttention": special_attention,
        },
    }


@tagged("onecore")
class TestSyncSpecialAttention(FlagSyncTestMixin, TransactionCase):
    def _request_with_tenant(self, contact_code="P123456", **tenant_vals):
        request = self._apartment_request(rental_id=FREE_RENTAL_ID)
        tenant = create_tenant(
            self.env,
            maintenance_request_id=request.id,
            contact_code=contact_code,
            **tenant_vals,
        )
        request.sudo().write({"tenant_id": tenant.id})
        return request, tenant

    def test_flag_set_in_xpand_after_creation_reaches_the_tenant(self):
        self._configure_onecore()
        request, tenant = self._request_with_tenant("P123456")
        self.assertFalse(tenant.special_attention)

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = [
                _contact("P123456", True)
            ]
            self.service.sync_special_attention()

        self.assertTrue(tenant.special_attention)
        self.assertTrue(request.special_attention)

    def test_cleared_flag_is_cleared_locally(self):
        self._configure_onecore()
        _request, tenant = self._request_with_tenant("P123456")
        tenant.sudo().write({"special_attention": True})

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = [
                _contact("P123456", False)
            ]
            self.service.sync_special_attention()

        self.assertFalse(tenant.special_attention)

    def test_code_missing_from_the_answer_is_left_alone(self):
        """Absent means unknown, not False."""
        self._configure_onecore()
        _request, tenant = self._request_with_tenant("P123456")
        tenant.sudo().write({"special_attention": True})

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = []
            self.service.sync_special_attention()

        self.assertTrue(tenant.special_attention)

    def test_codes_are_chunked(self):
        """Patch the size rather than create 200 records — the boundary logic
        is what matters, not the constant's value."""
        self._configure_onecore()
        self._request_with_tenant("P000001")
        self._request_with_tenant("P000002")
        self._request_with_tenant("P000003")

        with patch(CORE_API_PATH) as MockApi, patch.object(
            sync_module, "CONTACT_BATCH_SIZE", 2
        ):
            MockApi.return_value.fetch_contacts_batch.return_value = []
            self.service.sync_special_attention()

        calls = MockApi.return_value.fetch_contacts_batch.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0][0], ["P000001", "P000002"])
        self.assertEqual(calls[1][0][0], ["P000003"])

    def test_a_failing_chunk_does_not_lose_the_others(self):
        self._configure_onecore()
        _r1, tenant_one = self._request_with_tenant("P000001")
        _r2, tenant_two = self._request_with_tenant("P000002")

        with patch(CORE_API_PATH) as MockApi, patch.object(
            sync_module, "CONTACT_BATCH_SIZE", 1
        ):
            MockApi.return_value.fetch_contacts_batch.side_effect = [
                [_contact("P000001", True)],
                Exception("boom"),
            ]
            self.service.sync_special_attention()

        self.assertTrue(tenant_one.special_attention)
        self.assertFalse(tenant_two.special_attention)

    def test_closed_requests_are_excluded(self):
        self._configure_onecore()
        request, tenant = self._request_with_tenant("P123456")
        request.sudo().write({"closed_date": fields.Datetime.now()})

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = [
                _contact("P123456", True)
            ]
            self.service.sync_special_attention()

        self.assertFalse(tenant.special_attention)

    def test_unchanged_run_writes_nothing(self):
        self._configure_onecore()
        self._request_with_tenant("P123456")

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = [
                _contact("P123456", True)
            ]
            self.assertEqual(self.service.sync_special_attention(), 1)
            self.assertEqual(self.service.sync_special_attention(), 0)

    def test_unconfigured_onecore_is_a_no_op(self):
        self._request_with_tenant("P123456")

        with patch(CORE_API_PATH) as MockApi:
            self.assertEqual(self.service.sync_special_attention(), 0)

        MockApi.assert_not_called()
```

Add `create_tenant` to the `from ...utils.test_utils import (...)` block at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh`
Expected: FAIL — `AttributeError: 'OneCoreFlagSyncService' object has no attribute 'sync_special_attention'`.

- [ ] **Step 3: Add the batch size constant**

In `onecore_flag_sync_service.py`, after `_pest_set_cache`:

```python
# Codes per /v1/contacts/batch call. The endpoint takes a repeated ?code=
# param, so the practical ceiling is URL length, not a documented limit.
CONTACT_BATCH_SIZE = 200
```

- [ ] **Step 4: Add the two methods**

Append to the `OneCoreFlagSyncService` class:

```python
    # ------------------------------------------------------------------
    # Viktig kundinfo
    # ------------------------------------------------------------------
    def fetch_special_attention(self, contact_codes, api=None):
        """contact_code -> specialAttention, for the codes OneCore answered for.

        Codes missing from the result are missing on purpose: "unknown" must
        never be written as False. A chunk that fails is logged and skipped -
        unlike the pest set, each code stands on its own, so a partial answer
        is correct rather than dangerous.
        """
        codes = list(contact_codes)
        if not codes:
            return {}

        api = self._api(api)
        flags = {}
        for start in range(0, len(codes), CONTACT_BATCH_SIZE):
            chunk = codes[start : start + CONTACT_BATCH_SIZE]
            try:
                content = api.fetch_contacts_batch(chunk, timeout=LOOKUP_TIMEOUT)
            except Exception as err:
                _logger.warning(
                    "Viktig kundinfo: could not fetch %s contacts (from %s): %s",
                    len(chunk),
                    chunk[0],
                    err,
                )
                continue
            for contact in content or []:
                code = contact.get("contactCode")
                if not code:
                    continue
                communication = contact.get("communication") or {}
                flags[code] = bool(communication.get("specialAttention"))
        return flags

    def sync_special_attention(self, api=None):
        """Refresh special_attention on the tenants of every open request.

        The flag is snapshotted from the tenant payload when the case is
        created; without this it would never pick up a change made in Xpand
        afterwards. Returns the number of tenant records changed.
        """
        if not self.is_configured():
            _logger.info(
                "Viktig kundinfo-sync skipped: onecore_base_url is not set"
            )
            return 0

        tenants = self.open_requests().mapped("tenant_id")
        codes = sorted({t.contact_code for t in tenants if t.contact_code})
        if not codes:
            return 0

        flags = self.fetch_special_attention(codes, api=api)

        to_set, to_clear = [], []
        for tenant in tenants:
            desired = flags.get(tenant.contact_code)
            if desired is None:
                continue
            if desired and not tenant.special_attention:
                to_set.append(tenant.id)
            elif not desired and tenant.special_attention:
                to_clear.append(tenant.id)

        changed = self._apply(tenants, "special_attention", to_set, to_clear)
        _logger.info(
            "Viktig kundinfo-sync: %s codes asked, %s answered, %s set, "
            "%s cleared",
            len(codes),
            len(flags),
            len(to_set),
            len(to_clear),
        )
        return changed
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./run_tests.sh`
Expected: PASS — `TestSyncSpecialAttention` contributes 8 passing tests.

- [ ] **Step 6: Format and commit**

```bash
black onecore_maintenance_extension/models/services/onecore_flag_sync_service.py \
      onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py
git add onecore_maintenance_extension/models/services/onecore_flag_sync_service.py \
        onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py
git commit -m "feat(mim-1959): refresh viktig kundinfo from OneCore after case creation"
```

---

## Task 7: Odoo — populate the flag on the create path

**Files:**
- Modify: `onecore_maintenance_extension/models/services/onecore_flag_sync_service.py`
- Modify: `onecore_maintenance_extension/models/maintenance.py` (in `create()`, after `management_area_service.populate(request)` — currently line 1168)
- Test: `onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py`

**Interfaces:**
- Consumes: Task 5's `fetch_pest_blocked_rental_ids`, `get_rental_id`, `_pest_set_cache`, `PEST_SET_CACHE_TTL`
- Produces, on `OneCoreFlagSyncService`:
  - `cached_pest_blocked_rental_ids(api=None) -> frozenset[str]`
  - `populate_pest_control(request) -> bool`

- [ ] **Step 1: Write the failing test**

Append to `test_onecore_flag_sync_service.py`:

```python
@tagged("onecore")
class TestPopulateOnCreate(FlagSyncTestMixin, TransactionCase):
    def test_new_case_on_a_blocked_object_is_flagged_immediately(self):
        """Waiting up to a cron interval is exactly the window where the badge
        would have protected whoever is sent to the flat."""
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
            self.service.populate_pest_control(request)

        self.assertTrue(request.requires_pest_control)

    def test_new_case_on_a_free_object_is_not_flagged(self):
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            request = self._apartment_request(rental_id=FREE_RENTAL_ID)
            self.service.populate_pest_control(request)

        self.assertFalse(request.requires_pest_control)

    def test_onecore_failure_never_blocks_creation(self):
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_block_reason_captions.side_effect = (
                Exception("boom")
            )
            request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
            self.assertFalse(self.service.populate_pest_control(request))

        self.assertFalse(request.requires_pest_control)

    def test_a_burst_of_creations_shares_one_call(self):
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            api = self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            for _ in range(3):
                request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
                self.service.populate_pest_control(request)

        self.assertEqual(api.fetch_pest_blocked_rental_ids.call_count, 1)

    def test_the_cron_never_reads_the_create_cache(self):
        """A stale set is fine for one new case; it is not fine for a run that
        clears badges across the estate."""
        self._configure_onecore()
        sync_module._pest_set_cache[self.env.cr.dbname] = (
            time.monotonic() + 300,
            frozenset({BLOCKED_RENTAL_ID}),
        )
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)

        with patch(CORE_API_PATH) as MockApi:
            api = self._mock_api(MockApi, blocked=[])
            self.service.sync_pest_control()

        api.fetch_pest_blocked_rental_ids.assert_called_once()
        self.assertFalse(request.requires_pest_control)

    def test_create_populates_without_an_explicit_call(self):
        """The hook in create() is what makes this work in production."""
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            rental_property = create_rental_property(
                self.env, rental_property_id=BLOCKED_RENTAL_ID
            )
            request = create_maintenance_request(
                self.env,
                space_caption="Lägenhet",
                rental_property_id=rental_property.id,
            )

        self.assertTrue(request.requires_pest_control)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh`
Expected: FAIL — `AttributeError: 'OneCoreFlagSyncService' object has no attribute 'populate_pest_control'`.

- [ ] **Step 3: Add the cached fetch and the populate method**

In `onecore_flag_sync_service.py`, inside the "Spärr skadedjur" section, after `fetch_pest_blocked_rental_ids`:

```python
    def cached_pest_blocked_rental_ids(self, api=None):
        """TTL-cached blocked set, for the create path only.

        A burst of case creations shares one OneCore call. The cron must never
        use this: a stale set is harmless for one new case, but a run that
        clears badges across the estate has to see current truth.
        """
        key = self.env.cr.dbname
        cached = _pest_set_cache.get(key)
        if cached and time.monotonic() < cached[0]:
            return cached[1]

        blocked = frozenset(self.fetch_pest_blocked_rental_ids(api=api))
        _pest_set_cache[key] = (time.monotonic() + PEST_SET_CACHE_TTL, blocked)
        return blocked

    def populate_pest_control(self, request):
        """Stamp the pest flag on a freshly created request.

        Best effort, and never raises: OneCore being unreachable must not stop
        a handläggare - or an inbound mimer.nu request - from creating a case.
        The flag stays False and the next cron run heals it.
        """
        if not self.is_configured():
            return False
        rental_id = self.get_rental_id(request)
        if not rental_id:
            return False

        try:
            blocked = self.cached_pest_blocked_rental_ids()
        except Exception as err:
            _logger.warning(
                "Could not fetch pest blocks for new request %s: %s",
                request.id,
                err,
            )
            return False

        if rental_id not in blocked:
            return False

        request.sudo().with_context(skip_change_tracking=True).write(
            {"requires_pest_control": True}
        )
        return True
```

- [ ] **Step 4: Hook it into `create()`**

In `onecore_maintenance_extension/models/maintenance.py`, add the import to the existing services block (line 14-21):

```python
from .services import (
    FieldChangeTracker,
    RecordManagementService,
    FormFieldService,
    ExternalContractorService,
    MaintenanceStageManager,
    ManagementAreaService,
    OneCoreFlagSyncService,
)
```

Instantiate it next to the others (~line 1150):

```python
        management_area_service = ManagementAreaService(self.env)
        flag_sync_service = OneCoreFlagSyncService(self.env)
```

And call it directly after the management-area snapshot (~line 1168):

```python
            management_area_service.populate(request)
            # Spärr skadedjur, from the same TTL-cached set the cron refreshes.
            # Without this a case opened on a blocked flat shows no warning
            # until the next cron run (MIM-1959).
            flag_sync_service.populate_pest_control(request)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./run_tests.sh`
Expected: PASS — `TestPopulateOnCreate` contributes 6 passing tests, and no existing creation test regresses (the service no-ops when `onecore_base_url` is unset, which is the default in tests).

- [ ] **Step 6: Format and commit**

```bash
black onecore_maintenance_extension/models/services/onecore_flag_sync_service.py \
      onecore_maintenance_extension/models/maintenance.py \
      onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py
git add onecore_maintenance_extension/models/services/onecore_flag_sync_service.py \
        onecore_maintenance_extension/models/maintenance.py \
        onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py
git commit -m "feat(mim-1959): flag skadedjur on new cases without waiting for the cron"
```

---

## Task 8: Odoo — the two crons

**Files:**
- Modify: `onecore_maintenance_extension/models/maintenance.py` (next to `_cron_sync_kvv_areas` / `_cron_backfill_management_area`, ~line 1580-1595)
- Modify: `onecore_maintenance_extension/data/ir_cron.xml`
- Test: `onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py`

**Interfaces:**
- Consumes: Tasks 5 and 6's `sync_pest_control()` / `sync_special_attention()`
- Produces: `maintenance.request._cron_sync_pest_control()` and `._cron_sync_special_attention()`, plus the XML records `ir_cron_sync_pest_control` (15 min) and `ir_cron_sync_special_attention` (1 hour)

- [ ] **Step 1: Write the failing test**

Append to `test_onecore_flag_sync_service.py`:

```python
@tagged("onecore")
class TestFlagSyncCrons(FlagSyncTestMixin, TransactionCase):
    def test_pest_cron_delegates_to_the_service(self):
        self._configure_onecore()
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.env["maintenance.request"]._cron_sync_pest_control()

        self.assertTrue(request.requires_pest_control)

    def test_special_attention_cron_delegates_to_the_service(self):
        self._configure_onecore()
        request = self._apartment_request(rental_id=FREE_RENTAL_ID)
        tenant = create_tenant(
            self.env,
            maintenance_request_id=request.id,
            contact_code="P123456",
        )
        request.sudo().write({"tenant_id": tenant.id})

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = [
                {
                    "contactCode": "P123456",
                    "communication": {"specialAttention": True},
                }
            ]
            self.env["maintenance.request"]._cron_sync_special_attention()

        self.assertTrue(tenant.special_attention)

    def test_cron_records_exist_and_are_active(self):
        pest = self.env.ref(
            "onecore_maintenance_extension.ir_cron_sync_pest_control"
        )
        kundinfo = self.env.ref(
            "onecore_maintenance_extension.ir_cron_sync_special_attention"
        )

        self.assertTrue(pest.active)
        self.assertEqual(pest.interval_number, 15)
        self.assertEqual(pest.interval_type, "minutes")

        self.assertTrue(kundinfo.active)
        self.assertEqual(kundinfo.interval_number, 1)
        self.assertEqual(kundinfo.interval_type, "hours")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh`
Expected: FAIL — `_cron_sync_pest_control` does not exist, and `env.ref` raises `ValueError` for both external ids.

- [ ] **Step 3: Add the cron methods**

In `models/maintenance.py`, next to the existing cron entry points (~line 1595, after `_cron_backfill_management_area`):

```python
    @api.model
    def _cron_sync_pest_control(self):
        """Refresh "Spärr skadedjur" on every open request.

        One OneCore call per run regardless of case volume, so the interval can
        be short: a spärr added after the case was created has to reach the
        case (MIM-1959).
        """
        return OneCoreFlagSyncService(self.env).sync_pest_control()

    @api.model
    def _cron_sync_special_attention(self):
        """Refresh "Viktig kundinfo" on the tenants of every open request.

        Hourly rather than quarter-hourly: specialAttention is a hand-set flag
        in Xpand that changes very rarely, and this run costs one call per 200
        distinct contact codes.
        """
        return OneCoreFlagSyncService(self.env).sync_special_attention()
```

- [ ] **Step 4: Add the cron records**

In `onecore_maintenance_extension/data/ir_cron.xml`, inside `<data noupdate="1">` after `ir_cron_backfill_management_area`:

```xml
        <!--
        Spärr skadedjur on open requests. Cost per run is ONE call to
        /residences/rental-blocks/rental-ids regardless of how many cases are
        open, and only requests whose value actually changed are written - so a
        quiet run is a single SELECT. Short interval because the badge is a
        safety warning for whoever is sent to the address.
        -->
        <record id="ir_cron_sync_pest_control" model="ir.cron">
            <field name="name">Ärenden: synka spärr skadedjur från OneCore</field>
            <field name="model_id" ref="maintenance.model_maintenance_request"/>
            <field name="state">code</field>
            <field name="code">model._cron_sync_pest_control()</field>
            <field name="user_id" ref="base.user_root"/>
            <field name="interval_number">15</field>
            <field name="interval_type">minutes</field>
            <field name="active" eval="True"/>
        </record>

        <!--
        Viktig kundinfo on the tenants of open requests. specialAttention is
        snapshotted when the case is created and would otherwise never pick up
        a change made in Xpand afterwards. Hourly: the flag is set by hand and
        changes very rarely, and a run costs one call per 200 contact codes.
        -->
        <record id="ir_cron_sync_special_attention" model="ir.cron">
            <field name="name">Ärenden: synka viktig kundinfo från OneCore</field>
            <field name="model_id" ref="maintenance.model_maintenance_request"/>
            <field name="state">code</field>
            <field name="code">model._cron_sync_special_attention()</field>
            <field name="user_id" ref="base.user_root"/>
            <field name="interval_number">1</field>
            <field name="interval_type">hours</field>
            <field name="active" eval="True"/>
        </record>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./run_tests.sh`
Expected: PASS — `TestFlagSyncCrons` contributes 3 passing tests.

- [ ] **Step 6: Format and commit**

```bash
black onecore_maintenance_extension/models/maintenance.py \
      onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py
git add onecore_maintenance_extension/models/maintenance.py \
        onecore_maintenance_extension/data/ir_cron.xml \
        onecore_maintenance_extension/tests/models/services/test_onecore_flag_sync_service.py
git commit -m "feat(mim-1959): schedule the skadedjur and viktig kundinfo syncs"
```

---

## Task 9: Odoo — show the badge in kanban, list and mobile

**Files:**
- Modify: `onecore_maintenance_extension/views/maintenance_views.xml:946` (kanban field list), `:996` (list column), `:71` area (search filter)
- Modify: `onecore_maintenance_extension/static/src/views/maintenance_request_item.xml:14-18` (kanban badge)
- Modify: `onecore_maintenance_extension/views/mobile_view.xml:51` (mobile field) and its card template

**Interfaces:**
- Consumes: Task 4's stored `requires_pest_control`

The form already renders the badge (`maintenance_views.xml:176-181`) and needs no change — it now reads a stored value instead of computing one.

- [ ] **Step 1: Declare the field in the kanban view**

In `views/maintenance_views.xml`, directly after line 946 (`<field name="special_attention" />`):

```xml
                    <field name="requires_pest_control" />
```

- [ ] **Step 2: Add the badge to the kanban card**

In `static/src/views/maintenance_request_item.xml`, directly after the "Viktig kundinfo" block (lines 14-18), matching the form badge's colours:

```xml
                <div t-if="record.requires_pest_control.raw_value">
                    <span class="mimer-badge bg-warning text-dark">
                        Spärr skadedjur
                    </span>
                </div>
```

- [ ] **Step 3: Add the list column**

In `views/maintenance_views.xml`, directly after line 996 (`<field name="special_attention" optional="hide" />`):

```xml
                        <field name="requires_pest_control" optional="hide" />
```

- [ ] **Step 4: Add the search filters**

In `views/maintenance_views.xml`, after the "Olästa meddelanden" filter (~line 71-73) and before the `<separator />` that precedes the activity filters:

```xml
                        <separator />
                        <!-- special_attention is a related non-stored field and
                             cannot be searched directly; go through the stored
                             column on the tenant. requires_pest_control is
                             stored on the request itself. -->
                        <filter string="Viktig kundinfo" name="special_attention"
                            domain="[('tenant_id.special_attention', '=', True)]" />
                        <filter string="Spärr skadedjur" name="requires_pest_control"
                            domain="[('requires_pest_control', '=', True)]" />
```

- [ ] **Step 5: Declare the field in the mobile view**

The mobile view renders cards through the *same* OWL template as the kanban —
`onecore_ui/static/src/views/mobile_record.xml:6` is a bare
`<t t-call="onecore_maintenance_extension.maintenance_request_item"/>`. So the
badge from Step 2 is already there; the field just has to be loaded.

In `views/mobile_view.xml`, after line 51 (`<field name="special_attention" />`):

```xml
        <field name="requires_pest_control" />
```

Without this the template reads `record.requires_pest_control` on a record that
never fetched it, and the badge silently never renders on mobile.

- [ ] **Step 6: Verify the views load**

Run: `./run_tests.sh`
Expected: PASS. A malformed view or an undeclared field raises `ParseError` during module install, so a green run is the check that all four views are valid.

- [ ] **Step 7: Verify the badge renders in the real app**

Start the app, open the kanban, and confirm a case whose rental object carries an active SKADEDJUR block shows the orange "Spärr skadedjur" badge under the red "Viktig kundinfo" one. Confirm the same case's form still shows its badge, and that the list view's optional column and both search filters work.

Use the `run` skill if you need help launching the app.

- [ ] **Step 8: Commit**

```bash
git add onecore_maintenance_extension/views/maintenance_views.xml \
        onecore_maintenance_extension/views/mobile_view.xml \
        onecore_maintenance_extension/static/src/views/maintenance_request_item.xml
git commit -m "feat(mim-1959): show spärr skadedjur in kanban, list and mobile"
```

---

## Final verification

- [ ] **Full Odoo suite:** `./run_tests.sh` — all `onecore`-tagged tests pass
- [ ] **CoreApi suite:** `pytest onecore_api/tests/test_core_api.py`
- [ ] **onecore property suite:** `cd services/property && npx jest --config jest.config.js`
- [ ] **onecore core suite:** `cd core && npx jest`
- [ ] **Two PRs, correct targets:** onecore → `epic/mim-1983`; onecore-odoo → `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements`. Note in the onecore-odoo PR description that it depends on the onecore PR being deployed first.
