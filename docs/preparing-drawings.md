# DATAFY drawing release scope

DASHFY defaults to Official. Authorized Planning, Supply and administrator users
can select Official, Preparing or Both (`all`). Viewers always remain Official.
The selection applies only to records originating in DATAFY: drawing lists,
material demand and Procurement Plan links, including DATAFY drawing evidence
used by fabrication and 3D. In Both, canonical revision selection runs
independently for each release family; a Preparing revision cannot supersede an
Official document.

POs do not have Official/Preparing versions. Supply displays global PO and PO-line
totals, including orders without drawing allocations; switching drawing scope
does not change those totals. Drawing material coverage still describes the
selected drawings and must not be presented as a count of distinct POs.

Independent P6 schedules, MDR/DED workbooks, the external ECLIC register, imported
batch workbooks and panel comments keep their own complete data. They are not
classified or filtered using DATAFY's Preparing status, and a DATAFY outage does
not prevent independent engineering registers from loading or exporting.

Preparing material allocations are real reservations. Supply and fabrication
continue to read `catalog_stockpiece.remaining_qty` without filtering it by
document scope. Preparing reservations therefore remain unavailable to Official
materials. Visibility filtering must never be added to the global stock balance.
Unlinked P6 packages with an unknown/blank drawing remain in Official/Both.
An exact drawing + discipline identifies a known orphan's release family;
an identity present in both families appears only in Both, without inferred
progress links between the families.

## Deployment order

1. Deploy SPDM and apply its migration that adds
   `core_document.release_status` with the existing-document default `official`.
2. Deploy this DASHFY revision, apply accounts migration
   `0003_user_planning_supply_roles`, and restart its processes.
3. Refresh saved Supply snapshots if offline fallback is needed.

The source SQL requires the new column. If it is missing, the existing safe
source wrappers return an unavailable source; there is no unfiltered retry.
Supply snapshots require explicit matching `release_scope` and
`release_scope_version: 1` filters plus a matching payload marker
`drawing_release_scope: <scope>-v2`. Legacy and mismatched snapshots are ignored.
Source caches and the management dashboard also isolate payloads by release scope.

The 3D matcher chooses revisions within each release family and retains each
drawing's `release_status`. Exact-number recovery after revision replacement
cannot attach a package from one release family to the other.

## Users and interface

The administrator can select Planejamento (`planning`), Suprimentos (`supply`),
Administrador or Visualizador when creating or editing a user in Django admin.
Existing Analyst and Client accounts retain their roles and Official visibility;
no existing account is promoted automatically. Module and tenant permissions
remain independent. All authenticated users can open the cockpit.

The top bar's Datafy selector offers Official, Preparing and Both to authorized
profiles. It preserves filters and the current section. The server resolves the
authorized selection before loading DATAFY sources, including their API
requests, exports and snapshots. URLs carry the rendered selection so a second
tab cannot silently change the first tab's DATAFY data or exports. Viewers cannot select Preparing through
URL parameters, POST fields, a stale session or cached source payloads.

Supply snapshots must match both filters and the payload scope marker. Missing
PO totals in older snapshots are not inferred from drawing-coverage quantities.
Batch charts use the latest global workbook in every drawing selection.
Comments and minutes keep their existing project/client visibility. Existing
scope metadata on notes or batch workbooks is retained and ignored for filtering.
Legacy ECLIC pages retain module and tenant access rules without DATAFY reads.

## Verification

Run the focused permission and regression suites without operational databases:

```powershell
.\.venv\Scripts\python.exe manage.py test apps.accounts.tests apps.core.tests.test_release_scope_access apps.core.tests.test_release_scope_exports apps.core.tests.test_supply_release_snapshots apps.core.tests.test_data_origin_scope apps.core.tests.test_fabrication_batches apps.core.tests.test_release_scope_notes apps.eclic.test_release_scope --settings=config.test_settings --noinput
node --test apps/core/tests/test_dashboard_boot.cjs apps/core/tests/test_model_review.cjs apps/core/tests/test_model_progress_loading.cjs
```

The source suites also execute the real scope SQL against isolated fixtures and
check revision families, orphaned fabrication packages and shared reservations.
Browser QA used an isolated local demo for Planning and Viewer, including a
forged Preparing URL and a narrow viewport. Source-origin regressions check that
MDR, DED, batches and comments stay identical across selections and PO totals
stay global. No operational accounts were changed.
