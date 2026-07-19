from rest_framework import serializers
from django.contrib.auth.models import User
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.countries.models import Country
from components.workspace.api.workspace_permissions import IsOwnerOrReadOnly
from drf_writable_nested.serializers import WritableNestedModelSerializer

class CountrySerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Country
        fields = ['pk', 'name']
