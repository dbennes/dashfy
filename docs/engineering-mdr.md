# Engineering MDR

The engineering panel and engineering KPIs use the active PostgreSQL MDR import.
They no longer fall back to eClic. The yellow notice identifies Engineering as
the source and shows the dashboard import time in Africa/Lagos (WAT).

Administrators use **Importar MDR** in S01 to upload the Engineering `.xlsx`
or `.xlsm` file. A successful import replaces the active snapshot atomically;
an invalid workbook preserves the previous import.

The status chart and discipline table use **Document Status**. The source
descriptions remain available in tooltips; short labels use `(FOE)` except
for Finalized FOE and Finalized DED. The scope switch above the chart changes
both panels between all documents and ENG. CATEGORY **CAT 0/1 + CAT 2**.
The top-level AFC and Issued indicators retain the current **Code Status**
classification. Historical DED Code Status columns are not used as current data.

## First deployment

Push/pull transfers code, not the PostgreSQL imports. Transfer the supplied
workbook privately to the server, outside public static folders, then run:

```bash
python manage.py migrate --database default
python manage.py import_engineering_mdr "/private/path/FOE MDR - 23rd of September - Highlighted.xlsx" --initial-only
python manage.py collectstatic --noinput
python manage.py check
```

Restart the existing web service after the update. `--initial-only` leaves
an already active MDR untouched, including newer uploads. Omit this flag only
when intentionally importing a replacement workbook. Future updates can be
uploaded with **Importar MDR**, using the same parser as the command.

The supplied September workbook reconciles to **1,444 Overall** documents,
**1,067 Fabrication & Installation** documents and **13 disciplines**.
The eight Document Status counts are respectively
`35, 3, 5, 0, 275, 73, 264, 789` for Overall and
`35, 3, 5, 0, 260, 71, 264, 429` for Fabrication & Installation.
