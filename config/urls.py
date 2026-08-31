from django.contrib import admin
from django.urls import include, path

from ledger import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("grants/add/", views.add_grant, name="add_grant"),
    path("vests/add/", views.add_vest, name="add_vest"),
    path("sales/add/", views.add_sale, name="add_sale"),
    path("rates/add/", views.add_rate, name="add_rate"),
    path("access/", views.access_management, name="access_management"),
]
