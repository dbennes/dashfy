from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import datafy_supply
from apps.core.supply_snapshot_filters import (
    hash_supply_snapshot_filters,
    normalized_supply_snapshot_filters,
    scope_supply_filters,
    supply_snapshot_matches_scope,
)


class SupplySnapshotReleaseFiltersTests(SimpleTestCase):
    def test_release_status_changes_hash_and_business_filters_stay_normalized(self):
        hashes = {hash_supply_snapshot_filters({"release_scope": scope, "campaign": " a01 "})
                  for scope in ("official", "preparing", "all")}
        self.assertEqual(len(hashes), 3)
        self.assertEqual(hash_supply_snapshot_filters({"campaign": " a01 "}),
                         hash_supply_snapshot_filters({"campaign": "A01", "release_scope": "official"}))

    def test_legacy_normalization_is_pure_and_never_inherits_preparing(self):
        with patch("apps.core.release_scope.current_release_scope", return_value="preparing"):
            self.assertEqual(normalized_supply_snapshot_filters({})["release_scope"], "official")
            self.assertFalse(supply_snapshot_matches_scope({}, "official"))
            self.assertFalse(supply_snapshot_matches_scope({}, "preparing"))

    def test_live_filter_binding_uses_authorized_context_without_mutating_input(self):
        incoming = {"release_scope": "all", "campaign": "A01"}
        with patch("apps.core.release_scope.current_release_scope", return_value="preparing"):
            bound = scope_supply_filters(incoming)
        self.assertEqual(bound, {"release_scope": "preparing", "release_scope_version": 1, "campaign": "A01"})
        self.assertEqual(incoming["release_scope"], "all")

    def test_snapshot_requires_explicit_current_scope_and_contract_version(self):
        for scope in ("official", "preparing", "all"):
            self.assertTrue(supply_snapshot_matches_scope({"release_scope": scope, "release_scope_version": 1}, scope))
            self.assertFalse(supply_snapshot_matches_scope({"release_scope": scope}, scope))
            self.assertFalse(supply_snapshot_matches_scope({"release_scope": scope, "release_scope_version": 0}, scope))
        self.assertFalse(supply_snapshot_matches_scope({"release_scope": "preparing", "release_scope_version": 1}, "official"))


class SupplySnapshotReleasePersistenceTests(SimpleTestCase):
    @staticmethod
    def snapshot(pk, scope, *, explicit=True, marker=None, campaign="A01"):
        return SimpleNamespace(
            pk=pk, filters={"release_scope": scope, "release_scope_version": 1, "campaign": campaign} if explicit else {"campaign": campaign},
            payload={"drawing_release_scope": marker or f"{scope}-v2"},
        )

    @patch("apps.core.datafy_supply.DatafySupplySnapshot.objects")
    def test_latest_snapshot_rejects_legacy_and_cross_scope_even_when_hash_matches(self, manager):
        legacy = self.snapshot(1, "official", explicit=False)
        other = self.snapshot(2, "preparing")
        old_marker = self.snapshot(3, "official", marker="official-v1")
        expected = self.snapshot(4, "official")
        manager.filter.return_value.order_by.return_value = [legacy, other, old_marker, expected]
        with patch("apps.core.release_scope.current_release_scope", return_value="official"):
            result = datafy_supply.latest_supply_snapshot({"campaign": "A01"})
        self.assertIs(result, expected)
        manager.filter.assert_called_once_with(is_active=True, filters_hash=datafy_supply.supply_filters_hash({
            "campaign": "A01", "release_scope": "official", "release_scope_version": 1,
        }))

    @patch("apps.core.datafy_supply.cache.clear")
    @patch("apps.core.datafy_supply.transaction.atomic")
    @patch("apps.core.datafy_supply.DatafySupplySnapshot.objects")
    @patch("apps.core.datafy_supply._construction_datafy")
    def test_refresh_only_replaces_matching_scope_and_persists_authorized_filters(self, source, manager, atomic, clear):
        source.return_value = {"available": True, "drawing_release_scope": "preparing-v2",
                               "material_flow": {"total": 2}, "material_rows": [{"id": 4}]}
        snapshots = [self.snapshot(1, "official"), self.snapshot(2, "preparing"),
                     self.snapshot(3, "all"), self.snapshot(4, "preparing", explicit=False)]
        manager.filter.return_value.__iter__.return_value = iter(snapshots)
        with patch("apps.core.release_scope.current_release_scope", return_value="preparing"):
            datafy_supply.refresh_supply_snapshot({"campaign": "A01", "release_scope": "all"})
        bound = {"campaign": "A01", "release_scope": "preparing", "release_scope_version": 1}
        source.assert_called_once_with(bound)
        self.assertEqual(manager.filter.call_args_list[1].kwargs, {"pk__in": [2]})
        self.assertEqual(manager.create.call_args.kwargs["filters"], bound)
        self.assertEqual(manager.create.call_args.kwargs["filters_hash"], datafy_supply.supply_filters_hash(bound))
        clear.assert_called_once()

    @patch("apps.core.datafy_supply.DatafySupplySnapshot.objects")
    @patch("apps.core.datafy_supply._construction_datafy")
    def test_refresh_refuses_source_without_selected_scope_proof(self, source, manager):
        source.return_value = {"available": True, "drawing_release_scope": "all-v2"}
        with patch("apps.core.release_scope.current_release_scope", return_value="official"), self.assertRaises(ValueError):
            datafy_supply.refresh_supply_snapshot({})
        manager.create.assert_not_called()
