# 3D fabrication colours after drawing revision replacement

The 3D progress index reads active DATAFY fabrication packages. A drawing
replacement can clear a package's document foreign key through SET_NULL while
leaving its full drawing number and reported progress intact. Previously this
made the current drawing unlinked and omitted its progress overlay.

The index now selects the current revision using DATAFY's canonical revision
ordering, grouped by project and full drawing number. A package linked to a
superseded revision follows that drawing's current revision in the same project.
For a missing document link, the full drawing number must identify exactly one
current document in the package's discipline across the available projects.
Ambiguous matches remain unlinked. Partial drawing numbers and shortened line
tags cannot establish a link. Existing current document links retain precedence.

This is a read-only lookup. It does not modify fabrication packages, drawings,
source percentages or the existing completion and colour rules. In particular,
100% welding alone does not make an unfinished package completed.

Production investigation on 22 October 2026 found FB-149 / drawing
BNO-MABU-300-MP-2343-10162 with `linked: false`, while the current drawing
was present in the 3D index as unlinked. This explains the missing progress
colour for its piping line. The code change still needs deployment to DASHFY.

Validation: `python manage.py test apps.core.tests.test_model_review
apps.core.tests.test_model_review_tie_ins apps.core.tests.test_fabrication_weekly_progress`.
