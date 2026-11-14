from django.urls import path

from .views import ChannelComparisonView, DashboardSummaryView, HourlySalesView

urlpatterns = [
    path("summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("hourly-sales/", HourlySalesView.as_view(), name="dashboard-hourly-sales"),
    path("channels/", ChannelComparisonView.as_view(), name="dashboard-channels"),
]
