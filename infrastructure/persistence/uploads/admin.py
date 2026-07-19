from django.contrib import admin
from infrastructure.persistence.uploads.models import File

class FileAdmin(admin.ModelAdmin):
	pass

admin.site.register(File, FileAdmin)