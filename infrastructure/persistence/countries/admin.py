from django.contrib import admin
from infrastructure.persistence.countries.models import Country

class CountryAdmin(admin.ModelAdmin):
    list_display = ['name',]
    list_filter = ['name',]
    search_fields = ['name']
admin.site.register(Country, CountryAdmin)

