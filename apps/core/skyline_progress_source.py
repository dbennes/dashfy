"""Dated DATAFY fabrication observations, without inferring physical spool counts."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from . import fabrication_source as fabrication
from .skyline_completion_dates import build_completion_record, fabrication_planned_finish


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


def confirmed_actual_finish(package, as_of):
    """Return a supported actual finish, never a percentage/report-date proxy.

    A legacy package can supply its explicit actual date without stage detail.
    Available detail must agree: every applicable stage needs an actual finish,
    and each listed activity must have its own date with ``finish_actual=True``.
    Without a package date, a complete set of actual stage dates including
    painting can establish the finish of the retained fabrication scope.
    """
    cutoff = as_date(as_of)
    if cutoff is None:
        return None

    def actual_date(value):
        result = as_date(value)
        return result if result is not None and result <= cutoff else None

    raw_package_finish = package.get('actual_finish')
    package_finish = actual_date(raw_package_finish)
    if raw_package_finish not in (None, '') and package_finish is None:
        return None

    stages = fabrication._as_dict(package.get('stages'))
    marker = stages.get(fabrication.WEEKLY_PROGRESS_META_KEY, {})
    weekly = fabrication._weekly_overall_value(stages)
    pwht_requirement = (
        'stage_pwht_required'
        if isinstance(marker, dict) and marker.get('source') == fabrication.WEEKLY_PROGRESS_PMS_SOURCE
        else 'pwht_required'
    )
    stage_finishes = {}
    for key in fabrication.STAGE_KEYS:
        if key == 'pwht' and weekly is not None and marker.get(pwht_requirement) is False:
            continue
        stage = stages.get(key)
        if stage is None or stage == {}:
            continue
        if not isinstance(stage, dict):
            return None
        activities = stage.get('acts')
        if package_finish is not None and 'actual_finish' not in stage and activities in (None, []):
            # Old snapshots may retain only planned dates/percentages. Those
            # fields cannot contradict an explicit package actual date.
            continue
        stage_finish = actual_date(stage.get('actual_finish'))
        if stage_finish is None:
            return None
        if activities is not None:
            if not isinstance(activities, list):
                return None
            for activity in activities:
                if not isinstance(activity, dict) or activity.get('finish_actual') is not True:
                    return None
                activity_finish = actual_date(activity.get('finish'))
                if activity_finish is None or activity_finish > stage_finish:
                    return None
        stage_finishes[key] = stage_finish

    if package_finish is not None:
        return package_finish if all(value <= package_finish for value in stage_finishes.values()) else None
    if 'painting' not in stage_finishes:
        return None
    return max(stage_finishes.values())


def package_progress(package, entries, as_of):
    stages = fabrication._as_dict(package.get('stages'))
    marker = stages.get(fabrication.WEEKLY_PROGRESS_META_KEY, {})
    weekly = fabrication._weekly_overall_value(stages)
    observations = {}

    def observe(observed, value, source, filename='', completion=None):
        observed, value = as_date(observed), percent(value)
        if observed is not None and observed <= as_of and value is not None:
            previous_completion = observations.get(observed, {}).get('completion')
            observations[observed] = {
                'date': observed.isoformat(), 'pct': float(value), 'pct_exact': str(value),
                'source': source, 'source_filename': filename,
                'completion': completion or previous_completion or {},
            }

    # A P6 snapshot is an observation as of import, never an actual finish.
    if weekly is None and any(fabrication.stage_is_applicable(stages, key) for key in fabrication.STAGE_KEYS):
        observe(package.get('imported_at'), fabrication.overall_value(stages),
                'DATAFY P6 fabrication snapshot', package.get('source_workbook') or '')
    for entry in sorted(entries, key=lambda row: (str(row.get('progress_date') or ''), row.get('id') or 0)):
        values = fabrication._as_dict(entry.get('stages'))
        value = values.get('_overall_pct') if '_overall_pct' in values else entry.get('overall_after')
        observe(entry.get('progress_date'), value, 'DATAFY fabrication progress entry',
                values.get('_source_filename', ''), values.get('_completion'))
    if weekly is not None:
        source = ('EPC1 PMS weekly fabrication report' if marker.get('source') == fabrication.WEEKLY_PROGRESS_PMS_SOURCE
                  else 'EPC1 ISO weekly fabrication report')
        observe(marker.get('report_date'), weekly, source, marker.get('source_filename') or '', marker.get('completion'))

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
        'completion': build_completion_record(history, fabrication_planned_finish(stages), str(package['id']), as_of),
    }
