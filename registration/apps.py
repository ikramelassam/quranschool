from django.apps import AppConfig


class RegistrationConfig(AppConfig):
    name = 'registration'
    verbose_name = "Moteur d'inscription configurable"

    def ready(self):
        from . import signals  # noqa: F401
