from django.urls import path

from .views import OrderImportSampleView, OrderListView

urlpatterns = [
    path("", OrderListView.as_view(), name="order-list"),
    path("import-sample/", OrderImportSampleView.as_view(), name="order-import-sample"),
]
