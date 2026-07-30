from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.core.datafy_supply import supply_filters_hash
from apps.core.models import DatafySupplySnapshot
from apps.core.real_sources import (
    _construction_datafy_snapshot,
    _construction_filters,
    management_dashboard,
)
from apps.core.views import export_datafy_supply_view
from apps.eclic import api_client as eclic_api_client
from apps.eclic.api_client import EclicClient
from config.settings import _db_config


class PostgreSQLRuntimeTests(SimpleTestCase):
    def test_all_django_database_aliases_use_postgresql(self):
        engines = {
            alias: config["ENGINE"]
            for alias, config in settings.DATABASES.items()
        }

        self.assertTrue(engines)
        self.assertTrue(
            all(engine == "django.db.backends.postgresql" for engine in engines.values())
        )

    @patch.dict(os.environ, {"TASKFY_DB_NAME": "taskfy-do-not-migrate"}, clear=True)
    def test_main_database_name_never_falls_back_to_taskfy(self):
        config = _db_config(
            "DB",
            default_name="DASHFY",
            fallback_prefix="TASKFY_DB",
        )

        self.assertEqual(config["NAME"], "DASHFY")

    @patch("apps.core.real_sources._construction_datafy")
    def test_supply_reads_live_postgresql_before_persisted_snapshot(self, live_source):
        live_source.return_value = {"available": True}

        payload = _construction_datafy_snapshot({})

        self.assertEqual(payload["source_mode"], "postgres_live")
        self.assertEqual(payload["source_database"], settings.DATAFY_DB_NAME)
        live_source.assert_called_once_with({})

    @patch("apps.eclic.api_client._datafy_eclic_settings_fallback")
    def test_eclic_skips_datafy_fallback_when_config_is_complete(self, fallback):
        client = EclicClient(
            base_url="https://eclic.example",
            api_key="token",
            client_id=1,
            project_id=2,
        )

        fallback.assert_not_called()
        self.assertEqual(client.base_url, "https://eclic.example")

    @patch("psycopg2.connect")
    def test_eclic_does_not_cache_transient_datafy_failure(self, connect):
        import psycopg2

        connect.side_effect = psycopg2.OperationalError("DATAFY offline")
        eclic_api_client._cached_datafy_eclic_settings.cache_clear()
        try:
            self.assertEqual(eclic_api_client._datafy_eclic_settings_fallback(), {})
            self.assertEqual(eclic_api_client._datafy_eclic_settings_fallback(), {})
        finally:
            eclic_api_client._cached_datafy_eclic_settings.cache_clear()

        self.assertEqual(connect.call_count, 2)

    @patch("apps.core.real_sources.cache.set")
    @patch("apps.core.real_sources.cache.get", return_value=None)
    @patch("apps.core.real_sources._construction_datafy_snapshot")
    @patch("apps.core.real_sources._engineering_monitor_from_snapshot")
    @patch("apps.core.real_sources._engineering_from_ded_snapshot")
    @patch("apps.core.real_sources._construction_taskfy")
    @patch("apps.core.real_sources._p6_dashboard")
    def test_taskfy_outage_keeps_postgresql_engineering_imports(
        self,
        p6_dashboard,
        construction_taskfy,
        engineering_import,
        engineering_monitor,
        datafy_supply,
        _cache_get,
        _cache_set,
    ):
        p6_dashboard.return_value = {"kpis": {}, "charts": {}}
        construction_taskfy.side_effect = RuntimeError("Taskfy offline")
        engineering_import.return_value = {
            "source": "DED PostgreSQL",
            "source_mode": "postgres_snapshot",
            "error": "",
            "engineering_docs": 12,
            "engineering_counts": {
                "disciplines": 2,
                "revisions": 1,
                "issued": 4,
                "in_engineering": 8,
            },
            "engineering_flow": {"total": 12, "afc": 4, "afc_pct": 33.33},
            "engineering_summary": [],
            "engineering_discipline_groups": [],
            "engineering_revision_rows": [],
            "engineering_status_rows": [],
            "engineering_documents": [],
            "choices": {},
        }
        monitor_payload = {
            "source_mode": "postgres_import",
            "flow": {"total": 17},
        }
        engineering_monitor.return_value = monitor_payload
        datafy_supply.return_value = {
            "available": True,
            "source_mode": "postgres_live",
            "kpis": {},
            "charts": {},
        }

        payload = management_dashboard({})

        self.assertFalse(payload["taskfy"]["available"])
        self.assertEqual(
            payload["construction"]["engineering_monitor"],
            monitor_payload,
        )
        self.assertEqual(payload["construction"]["engineering_flow"]["total"], 12)

    @patch("apps.core.views.ExportLog.objects.create")
    @patch("apps.core.views.real_sources._construction_datafy_snapshot")
    def test_supply_export_uses_current_live_payload(self, supply_source, export_log):
        supply_source.return_value = {
            "available": True,
            "source_mode": "postgres_live",
            "source_database": "DATAFY",
            "source_host": "postgres:5432",
            "material_flow": {"total": 1},
            "supply_campaign_views": [{"totals": {"drawings": 1}}],
            "material_rows": [{"material_item_id": 99, "missing_qty": 2}],
        }
        request = RequestFactory().get("/datafy-supply/export/")
        request.user = SimpleNamespace(is_authenticated=True)

        response = export_datafy_supply_view(request)
        exported = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            exported["snapshot"]["payload"]["material_rows"][0]["material_item_id"],
            99,
        )
        self.assertEqual(exported["snapshot"]["source_mode"], "postgres_live")
        export_log.assert_called_once()


class PostgreSQLSnapshotFallbackTests(TestCase):
    def test_live_failure_uses_postgresql_snapshot_and_exposes_warning(self):
        filters = _construction_filters({})
        stored_filters = json.loads(json.dumps(filters, default=str))
        DatafySupplySnapshot.objects.create(
            source_database="DATAFY",
            source_host="postgres:5432",
            filters_hash=supply_filters_hash(filters),
            filters=stored_filters,
            payload={
                "available": True,
                "material_flow": {"total": 3},
                "material_rows": [{"material_item_id": 7}],
            },
            total_materials=3,
            total_drawings=1,
            material_rows=1,
        )

        with patch(
            "apps.core.real_sources._construction_datafy",
            side_effect=RuntimeError("DATAFY offline"),
        ):
            payload = _construction_datafy_snapshot(filters)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["source_mode"], "postgres_snapshot")
        self.assertEqual(payload["material_rows"][0]["material_item_id"], 7)
        self.assertIn("DATAFY offline", payload["source_warning"])

    def test_live_failure_without_snapshot_is_reported_unavailable(self):
        filters = _construction_filters({})

        with patch(
            "apps.core.real_sources._construction_datafy",
            side_effect=RuntimeError("DATAFY offline"),
        ):
            payload = _construction_datafy_snapshot(filters)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["source_mode"], "postgres_unavailable")
