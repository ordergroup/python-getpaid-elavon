from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class GetpaidElavonAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "getpaid_elavon"
    verbose_name = _("Elavon")

    def ready(self):
        from getpaid.registry import registry

        registry.register(self.module)
