"""Batch quantities from the SPS priority workbook; one listed item per data row."""
import hashlib
import re
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from openpyxl import load_workbook

from .models import FabricationBatchImport
from .release_scope import current_release_scope

MAX_BYTES = 10 * 1024 * 1024


def _key(value):
    return re.sub(r'[^A-Z0-9/.-]', '', str(value or '').upper())


def _batch(value):
    match = re.fullmatch(r'BATCH\s*(\d+)\s*(?:-\s*)?([A-Z]?)', str(value or '').strip().upper())
    if not match:
        raise ValueError(f'Invalid batch: {value!s}')
    return f'Batch {int(match[1])}{match[2]}'


def parse_workbook(content):
    try:
        book = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except (BadZipFile, OSError, ValueError) as exc:
        raise ValueError('Choose a valid .xlsx batch workbook.') from exc
    try:
        required = {'SPS BATCH 1-6', 'DUMMY SPOOLS'}
        if not required.issubset(book.sheetnames):
            raise ValueError('The workbook must contain SPS BATCH 1-6 and DUMMY SPOOLS.')
        sps = list(book['SPS BATCH 1-6'].values)
        dummy = list(book['DUMMY SPOOLS'].values)
        if (not sps or not dummy or len(sps[0]) < 12 or len(dummy[0]) < 6
                or _key(sps[0][8]) != 'BATCHNO.'
                or not _key(sps[0][11]).startswith('FABRICATION')
                or _key(dummy[0][2]) != 'LINENUMBER'
                or _key(dummy[0][5]) != 'FABRICATION'):
            raise ValueError('The batch workbook columns do not match the expected format.')
        lines, drawings = defaultdict(set), defaultdict(set)
        items, batches = [], set()
        line = drawing = ''
        excluded = 0
        for row_number, row in enumerate(sps[1:], 2):
            if not any(value is not None for value in row):
                continue
            drawing, line = row[1] or drawing, row[2] or line
            batch = _batch(row[8])
            batches.add(batch)
            if line:
                lines[_key(line)].add(batch)
            if drawing:
                drawings[_key(drawing)].add(batch)
            if not str(row[5] or '').strip().upper().startswith('SPS-'):
                excluded += 1
                continue
            items.append({'discipline': 'structural', 'batch': batch,
                          'done': _key(row[11]) == 'OK', 'row': row_number})
        unmapped = 0
        for row_number, row in enumerate(dummy[1:], 2):
            # Ignore titles, repeat headers and the blank half of merged rows.
            if not isinstance(row[0], (int, float)) or not row[2]:
                continue
            candidates = lines.get(_key(row[2])) or drawings.get(_key(row[3])) or set()
            batch = next(iter(candidates)) if len(candidates) == 1 else 'Unassigned'
            unmapped += batch == 'Unassigned'
            batches.add(batch)
            items.append({'discipline': 'piping', 'batch': batch,
                          'done': _key(row[5]) == 'OK', 'row': row_number})
        if not items:
            raise ValueError('No fabrication items were found in this workbook.')
        labels = sorted(batches, key=lambda b: (int(re.search(r'\d+', b)[0]), b) if b != 'Unassigned' else (99999, b))
        scopes = {}
        for scope in ('all', 'structural', 'piping'):
            selected = [item for item in items if scope == 'all' or item['discipline'] == scope]
            total = [sum(item['batch'] == label for item in selected) for label in labels]
            done = [sum(item['batch'] == label and item['done'] for item in selected) for label in labels]
            scopes[scope] = {'total': total, 'done': done, 'item_count': sum(total), 'done_count': sum(done)}
        return {'labels': labels, 'scopes': scopes, 'excluded_sps_rows': excluded, 'unassigned_items': unmapped}
    finally:
        book.close()


def import_workbook(upload, user=None):
    release_scope = current_release_scope()
    if release_scope == 'all':
        raise ValueError('Choose Official or Preparing before importing a batch workbook.')
    content = upload.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError('Maximum file size is 10 MB.')
    payload = parse_workbook(content)
    payload.update(release_scope=release_scope, release_scope_version=1)
    return FabricationBatchImport.objects.create(
        original_filename=Path(upload.name).name[:255],
        file_hash=hashlib.sha256(content).hexdigest(), payload=payload, imported_by_id=user.pk if user else None,
    )


def _payload_release_scope(payload):
    if not isinstance(payload, dict):
        return None
    # Existing workbooks predate Preparing and remain the Official baseline.
    if 'release_scope' not in payload:
        return 'official'
    if payload.get('release_scope_version') == 1 and payload.get('release_scope') in {'official', 'preparing'}:
        return payload['release_scope']
    return None


def _combined_batch_payload(snapshots):
    payloads = [snapshot.payload for snapshot in snapshots]
    labels = sorted({label for payload in payloads for label in payload['labels']},
                    key=lambda label: (int(re.search(r'\d+', label)[0]), label)
                    if label != 'Unassigned' else (99999, label))
    combined = {'labels': labels, 'scopes': {}, 'release_scope': 'all', 'release_scope_version': 1,
                'excluded_sps_rows': sum(payload.get('excluded_sps_rows', 0) for payload in payloads),
                'unassigned_items': sum(payload.get('unassigned_items', 0) for payload in payloads)}
    for scope in ('all', 'structural', 'piping'):
        totals, completed = defaultdict(int), defaultdict(int)
        for payload in payloads:
            for label, total, done in zip(payload['labels'], payload['scopes'][scope]['total'],
                                           payload['scopes'][scope]['done'], strict=True):
                totals[label] += total
                completed[label] += done
        total = [totals[label] for label in labels]
        done = [completed[label] for label in labels]
        combined['scopes'][scope] = {'total': total, 'done': done,
                                    'item_count': sum(total), 'done_count': sum(done)}
    return combined


def current_batches():
    release_scope = current_release_scope()
    requested = {'official', 'preparing'} if release_scope == 'all' else {release_scope}
    latest = {}
    for snapshot in FabricationBatchImport.objects.all():
        scope = _payload_release_scope(snapshot.payload)
        if scope in requested and scope not in latest:
            latest[scope] = snapshot
        if requested <= latest.keys():
            break
    if not latest:
        return {}
    snapshots = [latest[scope] for scope in ('official', 'preparing') if scope in latest]
    payload = _combined_batch_payload(snapshots) if release_scope == 'all' else snapshots[0].payload
    return {'payload': payload, 'filename': ' + '.join(snapshot.original_filename for snapshot in snapshots),
            'updated_at': max(snapshot.created_at for snapshot in snapshots),
            'release_scope': release_scope}


@login_required
@require_POST
def import_batches_view(request):
    if not getattr(request.user, 'is_admin', False):
        raise PermissionDenied('Only administrators can import batch data.')
    try:
        upload = request.FILES.get('batch_file')
        if not upload or not upload.name.lower().endswith('.xlsx'):
            raise ValueError('Choose the SPS / Dummy Spools .xlsx workbook.')
        snapshot = import_workbook(upload, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Batch fabrication updated: {snapshot.payload['scopes']['all']['item_count']} listed items.")
    return redirect(reverse('core:home') + f'?release_scope={current_release_scope()}#s03')
