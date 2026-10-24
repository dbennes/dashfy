from types import SimpleNamespace

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase

from apps.accounts.admin import UserAdmin
from apps.accounts.forms import ProfileForm, SignupForm
from apps.accounts.models import User
from apps.accounts.permissions import can_view_preparing


class PreparingRoleTests(SimpleTestCase):
    def test_only_explicit_admin_planning_and_supply_roles_can_view_preparing(self):
        for role in (User.Role.ADMIN, User.Role.PLANNING, User.Role.SUPPLY):
            with self.subTest(role=role):
                user = User(username=f"user-{role}", role=role)
                self.assertTrue(can_view_preparing(user))
                self.assertTrue(user.can_export)

    def test_legacy_analysts_clients_and_viewers_keep_official_only_access(self):
        for role in (User.Role.ANALYST, User.Role.CLIENT, User.Role.VIEWER):
            with self.subTest(role=role):
                user = User(username=f"legacy-{role}", role=role)
                self.assertFalse(can_view_preparing(user))
                self.assertFalse(user.is_admin)
        self.assertTrue(User(role=User.Role.ANALYST).can_export)
        self.assertTrue(User(role=User.Role.CLIENT).can_export)
        self.assertFalse(User(role=User.Role.VIEWER).can_export)

    def test_superuser_is_allowed_but_staff_flag_alone_does_not_grant_preparing(self):
        self.assertTrue(can_view_preparing(User(role=User.Role.VIEWER, is_superuser=True)))
        self.assertFalse(can_view_preparing(User(role=User.Role.VIEWER, is_staff=True)))

    def test_anonymous_missing_and_unauthenticated_users_are_denied(self):
        for user in (
            None, AnonymousUser(),
            SimpleNamespace(is_authenticated=False, role=User.Role.ADMIN, is_superuser=True),
        ):
            with self.subTest(user=user):
                self.assertFalse(can_view_preparing(user))

    def test_new_accounts_default_to_viewer_and_cannot_assign_own_role(self):
        self.assertEqual(User().role, User.Role.VIEWER)
        self.assertNotIn("role", SignupForm().fields)
        self.assertNotIn("role", ProfileForm().fields)
        for role in (User.Role.PLANNING, User.Role.SUPPLY):
            with self.subTest(role=role):
                self.assertFalse(User(role=role).is_admin)


class PreparingRoleAdminFormTests(SimpleTestCase):
    def setUp(self):
        self.admin = UserAdmin(User, AdminSite())
        self.request = RequestFactory().get("/admin/accounts/user/")
        self.request.user = User(username="administrator", is_staff=True, is_superuser=True)

    def test_admin_creation_and_change_forms_offer_new_and_legacy_profiles(self):
        user = User(username="existing-analyst", role=User.Role.ANALYST)
        for obj in (None, user):
            with self.subTest(creating=obj is None):
                form = self.admin.get_form(self.request, obj=obj)()
                values = {value for value, _label in form.fields["role"].choices}
                self.assertTrue({"admin", "planning", "supply", "viewer", "analyst", "client"}.issubset(values))
        self.assertEqual(user.role, User.Role.ANALYST)

    def test_admin_can_explicitly_assign_planning_or_supply_without_other_profile_changes(self):
        for role in (User.Role.PLANNING, User.Role.SUPPLY):
            with self.subTest(role=role):
                user = User(username="existing-viewer", role=User.Role.VIEWER)
                form_class = self.admin.get_form(self.request, obj=user, fields=("role",))
                form = form_class(data={"role": role}, instance=user)
                self.assertTrue(form.is_valid(), form.errors)
                updated = form.save(commit=False)
                self.assertEqual(updated.role, role)
                self.assertFalse(updated.is_staff)
                self.assertFalse(updated.is_superuser)
