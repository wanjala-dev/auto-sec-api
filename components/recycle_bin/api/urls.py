from django.urls import path

from .controller import (
    RecycleBinDeleteOneView,
    RecycleBinEmptyView,
    RecycleBinListView,
    RecycleBinRestoreView,
    RecycleBinTrashBulkView,
    RecycleBinTrashView,
)

urlpatterns = [
    path('', RecycleBinListView.as_view(), name='recycle-bin-list'),
    path('trash/', RecycleBinTrashView.as_view(), name='recycle-bin-trash'),
    path('trash/bulk/', RecycleBinTrashBulkView.as_view(), name='recycle-bin-trash-bulk'),
    path('empty/', RecycleBinEmptyView.as_view(), name='recycle-bin-empty'),
    path('<uuid:entry_id>/restore/', RecycleBinRestoreView.as_view(), name='recycle-bin-restore'),
    path('<uuid:entry_id>/', RecycleBinDeleteOneView.as_view(), name='recycle-bin-delete'),
]
