"""URL routing for the search context API.

Mounted at ``search/`` in the root URL configuration (and therefore also
under ``/api/v0/`` and ``/api/v1/`` via the versioned includes).
"""

from django.urls import path

from components.search.api.controller import SearchSuggestController

urlpatterns = [
    path("suggest/", SearchSuggestController.as_view(), name=SearchSuggestController.name),
]
