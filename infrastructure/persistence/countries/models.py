from django.db import models

# Create your models here.


class Country(models.Model):
    name = models.CharField(max_length=200, unique=True, default='Canada', primary_key=True, editable=True, null=False)
    class Meta:
        ordering = ('name',)
        db_table = "country"
    def __str__(self):
        return self.pk
