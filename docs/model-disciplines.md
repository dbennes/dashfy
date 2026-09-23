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
