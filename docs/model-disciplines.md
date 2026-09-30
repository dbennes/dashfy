# 3D discipline visibility

In the model toolbar, open **Visible disciplines** and check/uncheck groups.
**Show all disciplines** restores visibility without changing the camera or
clearing the current selection. Filters last while the page is open. Selection
isolation remains separate: use **Show all** on the selection bar to exit it.

The same filter applies to fast preview, HQ, exact selected surfaces, DATAFY
overlays and piping progress. Hidden disciplines are excluded from click picks.
Groups come from the authored level-3 model hierarchy, not drawing availability:

The sidebar tree and visibility menu share the same nine categories and order.
Model groups are listed even when they have no linked drawing. Tie-in groups
belong to **Piping**, including all their descendants; standalone geometry
outside discipline groups is listed under **Other items**. Supports are separate
from Structural in both controls.

| Model suffix | Checkbox |
| --- | --- |
| PIPE | Piping |
| TIE-IN-POINTS (including TAM-26) | Piping |
| STRU, WIT, FRMW | Structural |
| ELEC | Electrical |
| INST | Instrumentation |
| EQUI | Equipment |
| PSUP, PUSP | Supports |
| TELE | Telecom |
| PAUX | Auxiliary |
| Unrecognised / outside those groups | Other items |

## Assets

`static/models/bonga-2-disciplines-fast.glb` and
`static/models/bonga-2-disciplines-hq.glb` retain independent discipline parents,
with geometry batched inside each group. HQ retains 9,439,364 triangles and 19
mesh primitives. Original files remain available.

To rebuild after replacing the source model and its matching hierarchy, use the
project virtual environment and the official gltfpack 1.1 build utility:

```powershell
python tools/build_model_disciplines.py --gltfpack C:/path/to/gltfpack.exe
```

The utility writes intermediates under `tmp/` and the two final assets plus
reports under `static/models/`. It does not run on page loads or on the server.
Publish both GLBs with the frontend changes and run the normal `collectstatic`
deployment step. No database migration is needed.

Regression checks:

```powershell
node --test apps/core/tests/test_model_disciplines.cjs apps/core/tests/test_model_review.cjs apps/core/tests/test_model_navigation.cjs apps/core/tests/test_model_surroundings.cjs apps/core/tests/test_render_idle.cjs
python manage.py check
```

## Expanded review and progressive fabrication colours

`Expand review` opens the existing viewer in a large native dialog. It moves
the live DOM rather than cloning the canvas or creating another renderer.
Camera position, selected item, discipline visibility, navigation and colours
survive closing/reopening. Escape closes the dialog without clearing selection.
On small screens, `Model tree` opens the search and hierarchy beside the viewer.

Progress colours appear as exact line geometry becomes available: the first
successful line immediately, followed by batches of up to eight completed
requests. Two workers leave capacity for selection requests. Returning to Normal
aborts unfinished geometry downloads; HQ refinement does not restart colouring.
Failed geometry is reported and choosing Progress again retries a partial result.
Requests for links time out after 30 seconds and each geometry fetch after 45
seconds, allowing retry instead of an indefinite loading state.

The server retains one source model header and computes transforms only for
selected nodes and their ancestors. The source path, size and modification time
invalidate that metadata. Fabrication statuses are not cached by this change.
Selection files are written atomically and simultaneous requests for the same
node are coalesced within each process.

Local benchmark on eight active piping lines, with no selection cache:
19.039 seconds before, 0.936 seconds after; all eight GLBs had identical SHA256
hashes. This measures geometry generation, not production network/download time.
Deploy code and static assets, then restart the application; no migration needed.

## Drawing and line identifiers

Line matching uses the complete tag. Optional paired quotes around a numeric
class are ignored in both the drawing index and model hierarchy: for example,
`4"-PG-313050-750-FFLT-1H` matches `/4"-PG-313050-"750"-FFLT-1H`.
Diameter inch marks, fractional sizes, line numbers, suffixes and branches remain
significant. Searching for a drawing or the last digits of a line does not create
an association to a different line.

For TAM26 tie-ins, the stored line field can omit the tie-in prefix or truncate a
fraction. The review recovers the complete identifier only from a unique title
block in that same drawing's extracted text: identifier, sheet number, total
sheets, class, then the exact drawing number. The suffix must match the stored
tag, or continue that tag at a slash. Continuation references elsewhere in the
drawing are excluded. Tie-ins keep their own geometry and fabrication status,
separate from the main line. Extracted text is not sent to the browser and source
records are not modified.

If neither exact identifier exists in the model, the viewer continues to report
`no exact 3D match`; resolving that case requires correcting the source data or
supplying the missing geometry.

Identifier regressions:

```powershell
node --test apps/core/tests/test_model_review.cjs
python manage.py test apps.core.tests.test_model_review apps.core.tests.test_model_review_tie_ins apps.core.tests.test_model_selection
```
