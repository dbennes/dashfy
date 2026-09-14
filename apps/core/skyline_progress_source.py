"""Dated DATAFY fabrication observations, without inferring physical spool counts."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from . import fabrication_source as fabrication


def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def percent(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and 0 <= result <= 100 else None


def is_complete(value):
    # Excel's binary arithmetic can persist 100% as 99.99999999999999.
    # This tolerance is solely for that noise; 99.99% remains partial.
    value = percent(value)
    return value is not None and Decimal('100') - value <= Decimal('0.000000001')


def package_progress(package, entries, as_of):
    stages = fabrication._as_dict(package.get('stages'))
    marker = stages.get(fabrication.WEEKLY_PROGRESS_META_KEY, {})
    weekly = fabrication._weekly_overall_value(stages)
    observations = {}

    def observe(observed, value, source, filename=''):
        observed, value = as_date(observed), percent(value)
        if observed is not None and observed <= as_of and value is not None:
            observations[observed] = {
                'date': observed.isoformat(), 'pct': float(value), 'pct_exact': str(value),
                'source': source, 'source_filename': filename,
            }

    # A P6 snapshot is an observation as of import, never an actual finish.
    if weekly is None and any(fabrication.stage_is_applicable(stages, key) for key in fabrication.STAGE_KEYS):
        observe(package.get('imported_at'), fabrication.overall_value(stages),
                'DATAFY P6 fabrication snapshot', package.get('source_workbook') or '')
    for entry in sorted(entries, key=lambda row: (str(row.get('progress_date') or ''), row.get('id') or 0)):
        values = fabrication._as_dict(entry.get('stages'))
        value = values.get('_overall_pct') if '_overall_pct' in values else entry.get('overall_after')
        observe(entry.get('progress_date'), value, 'DATAFY fabrication progress entry')
    if weekly is not None:
        source = ('EPC1 PMS weekly fabrication report' if marker.get('source') == fabrication.WEEKLY_PROGRESS_PMS_SOURCE
                  else 'EPC1 ISO weekly fabrication report')
        observe(marker.get('report_date'), weekly, source, marker.get('source_filename') or '')

    history = [observations[key] for key in sorted(observations)]
    latest = history[-1] if history else {}
    completed_date = ''
    for observation in history:
        if is_complete(observation['pct_exact']):
            completed_date = completed_date or observation['date']
        else:
            completed_date = ''
    return {
        'package_id': package['id'], 'package_code': package.get('code') or '',
        'pct': latest.get('pct'), 'pct_exact': latest.get('pct_exact'),
        'source': latest.get('source', ''), 'source_filename': latest.get('source_filename', ''),
        'as_of_date': latest.get('date', ''), 'completed_date': completed_date,
        'history': history,
    }
