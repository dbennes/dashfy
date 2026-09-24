"""Discard empty Excel formatting while retaining cells for import validation."""
from io import BytesIO
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.parsers import expat
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter

MAX_EXPANDED = 256 * 1024 * 1024
MAX_DATA = 50 * 1024 * 1024
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def compact_sheet(source, budget):
    output = BytesIO()
    row = None
    stack = []
    max_row = max_col = 1
    text_bytes = 0
    parser = expat.ParserCreate(namespace_separator="}")

    def tag(name):
        return "{" + name if "}" in name else name

    def start(name, attrs):
        nonlocal row
        name = tag(name)
        attrs = {tag(key): value for key, value in attrs.items()}
        if name == f"{{{NS}}}row":
            row = Element(name, attrs)
        elif name == f"{{{NS}}}c" and row is not None:
            stack.append(Element(name, attrs))
        elif stack:
            stack.append(SubElement(stack[-1], name, attrs))

    def text(value):
        nonlocal text_bytes
        if stack:
            text_bytes += len(value.encode("utf-8"))
            if text_bytes > budget:
                raise ValueError("Workbook data exceeds the limit: 50 MB after removing empty formatting.")
            element = stack[-1]
            element.text = (element.text or "") + value

    def end(name):
        nonlocal row, max_row, max_col
        name = tag(name)
        if stack:
            element = stack.pop()
            if name == f"{{{NS}}}c":
                # Preserve strings and values, including zero. Use Excel's saved
                # formula result; never execute formulas on the server. Leave
                # uncached formulas intact so the existing validator rejects them.
                if any(child.tag in (f"{{{NS}}}v", f"{{{NS}}}f", f"{{{NS}}}is") for child in element):
                    try:
                        r, c = coordinate_to_tuple(element.attrib["r"])
                    except (ValueError, KeyError) as exc:
                        raise ValueError("Workbook contains an invalid cell address.") from exc
                    if c > 8:
                        return  # Auxiliary calculation columns are not imported.
                    formula = element.find(f"{{{NS}}}f")
                    value = element.find(f"{{{NS}}}v")
                    if formula is not None and value is not None and (
                        value.text is not None or element.get("t") == "str"
                    ):
                        element.remove(formula)
                    max_row, max_col = max(max_row, r), max(max_col, c)
                    row.append(element)
        elif name == f"{{{NS}}}row" and row is not None:
            if len(row):
                output.write(tostring(row, encoding="utf-8"))
                if output.tell() > budget:
                    raise ValueError("Workbook data exceeds the limit: 50 MB after removing empty formatting.")
            row = None

    def reject_doctype(*args):
        raise ValueError("Workbook XML must not contain a document type declaration.")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = reject_doctype
    try:
        while chunk := source.read(64 * 1024):
            parser.Parse(chunk, False)
        parser.Parse(b"", True)
    except expat.ExpatError as exc:
        raise ValueError("Workbook XML is invalid. Export a new workbook.") from exc
    header = (f'<worksheet xmlns="{NS}"><dimension ref="A1:{get_column_letter(max_col)}{max_row}"/>'
              '<sheetData>').encode()
    return header + output.getvalue() + b"</sheetData></worksheet>"


def compact_workbook(content):
    """Bound raw expansion, then bound retained data after stripping empty cells.

    Preserve cell types/styles, saved formula results and signed metadata.
    Import A:H only; additional columns may contain users' helper calculations.
    Process one row at a time so formatting across a million rows stays bounded.
    """
    output = BytesIO()
    with ZipFile(BytesIO(content)) as source:
        entries = source.infolist()
        if len(entries) > 200:
            raise ValueError(f"Workbook contains {len(entries)} internal files (limit: 200).")
        expanded = sum(item.file_size for item in entries)
        if expanded > MAX_EXPANDED:
            raise ValueError(f"Workbook expands to {expanded / (1024 * 1024):.1f} MB (limit: 256 MB). "
                             "Remove unused formatting or paste your values into a fresh export.")
        total = 0
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as target:
            for item in entries:
                is_sheet = item.filename.startswith("xl/worksheets/") and item.filename.endswith(".xml")
                if is_sheet:
                    with source.open(item) as stream:
                        data = compact_sheet(stream, MAX_DATA - total)
                else:
                    if total + item.file_size > MAX_DATA:
                        raise ValueError("Workbook data exceeds the limit: 50 MB after removing empty formatting.")
                    data = source.read(item)
                total += len(data)
                if total > MAX_DATA:
                    raise ValueError("Workbook data exceeds the limit: 50 MB after removing empty formatting.")
                target.writestr(item.filename, data)
    return output.getvalue()
