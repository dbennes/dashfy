from copy import deepcopy
from datetime import date

from django.test import SimpleTestCase

from apps.core.skyline_progress_source import confirmed_actual_finish


class SkylineActualFinishEvidenceTests(SimpleTestCase):
    as_of = date(2026, 9, 14)

    def stage(self, finished='2026-09-10', **activity_changes):
        return {
            'pct': 100,
            'actual_finish': finished,
            'acts': [{'id': 'ACT-1', 'finish': finished, 'finish_actual': True, **activity_changes}],
        }

    def test_explicit_legacy_package_date_is_accepted_without_stage_detail(self):
        package = {'actual_finish': '2026-09-10', 'stages': {'_wbs': {'path': ['Fabrication']}}}
        self.assertEqual(confirmed_actual_finish(package, self.as_of), date(2026, 9, 10))

    def test_legacy_planned_only_stage_cannot_contradict_explicit_package_actual_date(self):
        package = {'actual_finish': '2026-09-10', 'stages': {
            'painting': {'pct': 0, 'plan_finish': '2026-09-18'},
        }}
        self.assertEqual(confirmed_actual_finish(package, self.as_of), date(2026, 9, 10))
        package['stages']['painting']['actual_finish'] = None
        self.assertIsNone(confirmed_actual_finish(package, self.as_of))

    def test_all_stages_and_activities_including_painting_establish_latest_real_finish(self):
        package = {'stages': {
            'prefabrication': self.stage('2026-09-01'),
            'welding': self.stage('2026-09-04'),
            'painting': self.stage('2026-09-11'),
        }}
        original = deepcopy(package)
        self.assertEqual(confirmed_actual_finish(package, self.as_of), date(2026, 9, 11))
        self.assertEqual(package, original)

    def test_percentage_plan_and_weekly_report_cannot_supply_an_actual_finish(self):
        package = {
            'plan_finish': '2026-09-10', 'imported_at': '2026-09-14',
            'stages': {
                'painting': {'pct': 100, 'plan_finish': '2026-09-10'},
                '_weekly_progress': {
                    'schema': 1, 'source': 'epc1_pms_weekly', 'mode': 'overall_only',
                    'report_date': '2026-09-11', 'overall_pct': '100',
                },
            },
        }
        self.assertIsNone(confirmed_actual_finish(package, self.as_of))

    def test_explicit_package_date_cannot_hide_an_undated_or_unfinished_activity(self):
        for changes in ({'finish_actual': False}, {'finish_actual': 1},
                        {'finish': None}, {'finish': True}, {'finish': '2026-09-18'}):
            with self.subTest(changes=changes):
                package = {'actual_finish': '2026-09-12', 'stages': {
                    'welding': self.stage(**changes), 'painting': self.stage('2026-09-12'),
                }}
                self.assertIsNone(confirmed_actual_finish(package, self.as_of))

    def test_missing_actual_stage_finish_blocks_package_completion(self):
        for actual in (None, True, '2026-09-18'):
            with self.subTest(actual=actual):
                stage = self.stage()
                stage['actual_finish'] = actual
                package = {'actual_finish': '2026-09-12', 'stages': {'painting': stage}}
                self.assertIsNone(confirmed_actual_finish(package, self.as_of))

    def test_missing_painting_never_derives_completion_from_other_finished_stages(self):
        package = {'stages': {'welding': self.stage()}}
        self.assertIsNone(confirmed_actual_finish(package, self.as_of))

    def test_only_valid_weekly_not_applicable_marker_can_exclude_unfinished_pwht(self):
        for source, requirement_key in (('epc1_iso_weekly', 'pwht_required'),
                                        ('epc1_pms_weekly', 'stage_pwht_required')):
            with self.subTest(source=source):
                marker = {
                    'schema': 1, 'source': source, 'report_date': '2026-09-11',
                    'overall_pct': '100', requirement_key: False,
                }
                if source == 'epc1_pms_weekly':
                    marker['mode'] = 'overall_only'
                package = {'stages': {
                    'painting': self.stage(), 'pwht': {'pct': 0, 'actual_finish': None},
                    '_weekly_progress': marker,
                }}
                self.assertEqual(confirmed_actual_finish(package, self.as_of), date(2026, 9, 10))
                marker[requirement_key] = True
                self.assertIsNone(confirmed_actual_finish(package, self.as_of))
                marker[requirement_key] = False
                marker['source'] = 'unsupported'
                self.assertIsNone(confirmed_actual_finish(package, self.as_of))

    def test_future_and_boolean_package_dates_are_never_actual_dates(self):
        for value in ('2026-09-18', True, False, 'invalid'):
            with self.subTest(value=value):
                self.assertIsNone(confirmed_actual_finish({'actual_finish': value}, self.as_of))

    def test_earlier_aggregate_dates_cannot_hide_later_activity_or_stage_finishes(self):
        package = {'stages': {'painting': self.stage('2026-09-10', finish='2026-09-11')}}
        self.assertIsNone(confirmed_actual_finish(package, self.as_of))
        package = {'actual_finish': '2026-09-09', 'stages': {'painting': self.stage()}}
        self.assertIsNone(confirmed_actual_finish(package, self.as_of))

    def test_aggregate_stage_actual_dates_support_legacy_stages_without_activity_lists(self):
        package = {'stages': {
            'welding': {'actual_finish': '2026-09-04'},
            'painting': {'actual_finish': '2026-09-11'},
        }}
        self.assertEqual(confirmed_actual_finish(package, self.as_of), date(2026, 9, 11))
