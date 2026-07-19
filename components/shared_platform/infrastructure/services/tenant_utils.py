import os
from django.db import connection
from django.conf import settings
#from .models import Tenant

def hostname_from_request(request):
    # split on `:` to remove port
    return request.get_host().split(":")[0].lower()


def tenant_db_from_request(request):
    hostname = hostname_from_request(request)
    tenants_map = get_tenants_map()
    return tenants_map.get(hostname)

def get_tenants_map():
    return {
        settings.WORKSPACE_API_URL: "workspace",
        settings.ART_API_URL: "art",
        settings.LTG_API_URL: "ltg",
    }

# def get_tenants_map():
#     tenants = Tenant.objects.all()
#     print("TENANTS::", tenants)
#     return {tenant.hostname: tenant.database_name for tenant in tenants}
