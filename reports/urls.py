from django.urls import path

from .views import CategoryReviewsView, ReportView

urlpatterns = [
    path("", ReportView.as_view(), name="report-detail"),
    path("reviews/", CategoryReviewsView.as_view(), name="report-evidence-reviews"),
]
