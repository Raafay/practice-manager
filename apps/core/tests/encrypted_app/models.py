from django.db import models

from apps.core.fields import EncryptedTextField


class Secret(models.Model):
    label = models.CharField(max_length=50)
    value = EncryptedTextField(blank=True, null=True)

    def __str__(self) -> str:
        return self.label
