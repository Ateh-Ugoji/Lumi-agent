"""Read-only admin base that can never show an encrypted column.

Every model registered in the admin goes through :class:`SafeModelAdmin`. It hides each
``EncryptedTextField`` from forms, read-only fields, list columns, filters and search, so the
decrypted value cannot reach a page. It is also read-only: the admin is for reviewing data
(imported rows, jobs, alerts), not for editing it, and saving a form could not round-trip a hidden
column. The system check ``lumi.E001`` fails startup when a model with an encrypted field is
registered with any other admin class.
"""

from __future__ import annotations

from django.contrib import admin
from django.core import checks
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import BackgroundJob, LegacyImportMap


def encrypted_field_names(model: type[models.Model]) -> frozenset[str]:
    return frozenset(
        field.name
        for field in model._meta.get_fields()
        if isinstance(field, EncryptedTextField)
    )


def _base_name(entry: str) -> str:
    """``^email``, ``handle__name`` and ``user__email__icontains`` all start with a field name."""
    return entry.lstrip("^=@$").split("__", 1)[0]


class SafeModelAdmin(admin.ModelAdmin):
    show_full_result_count = False
    list_per_page = 50

    def __init__(self, model, admin_site):
        # Foreign keys as id inputs: a select with every post would never finish loading.
        self.raw_id_fields = tuple(
            dict.fromkeys(
                (
                    *self.raw_id_fields,
                    *(
                        f.name
                        for f in model._meta.get_fields()
                        if isinstance(f, models.ForeignKey | models.OneToOneField)
                    ),
                )
            )
        )
        super().__init__(model, admin_site)

    @property
    def _hidden(self) -> frozenset[str]:
        return encrypted_field_names(self.model)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_exclude(self, request, obj=None):
        return (*(super().get_exclude(request, obj) or ()), *sorted(self._hidden))

    def get_fields(self, request, obj=None):
        return [f for f in super().get_fields(request, obj) if f not in self._hidden]

    def get_readonly_fields(self, request, obj=None):
        return [
            f
            for f in super().get_readonly_fields(request, obj)
            if f not in self._hidden
        ]

    def get_list_display(self, request):
        return [c for c in super().get_list_display(request) if c not in self._hidden]

    def get_list_filter(self, request):
        return [c for c in super().get_list_filter(request) if c not in self._hidden]

    def get_search_fields(self, request):
        return [
            c
            for c in super().get_search_fields(request)
            if _base_name(c) not in self._hidden
        ]


@checks.register()
def check_admin_hides_encrypted_fields(app_configs, **kwargs):
    errors = []
    for model, model_admin in admin.site._registry.items():
        hidden = encrypted_field_names(model)
        if hidden and not isinstance(model_admin, SafeModelAdmin):
            errors.append(
                checks.Error(
                    f"{model.__name__} tiene campos cifrados ({', '.join(sorted(hidden))}) "
                    f"y su admin no hereda de apps.core.admin.SafeModelAdmin.",
                    obj=type(model_admin),
                    id="lumi.E001",
                )
            )
    return errors


@admin.register(BackgroundJob)
class BackgroundJobAdmin(SafeModelAdmin):
    list_display = (
        "id",
        "kind",
        "status",
        "progress",
        "user",
        "profile",
        "created_at",
        "finished_at",
    )
    list_filter = ("kind", "status")
    ordering = ("-created_at",)


@admin.register(LegacyImportMap)
class LegacyImportMapAdmin(SafeModelAdmin):
    list_display = (
        "id",
        "source_table",
        "source_pk",
        "target_table",
        "target_pk",
        "outcome",
        "imported_at",
    )
    list_filter = ("source_table", "target_table", "outcome")
    search_fields = ("source_pk", "target_pk")
    ordering = ("-id",)
