from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from ledger import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("ledgers/switch/", views.switch_workspace, name="switch_workspace"),
    path("ledgers/create/", views.create_workspace, name="create_workspace"),
    path("grants/", views.grant_list, name="grant_list"),
    path("grants/add/", views.add_grant, name="add_grant"),
    path("grants/<int:grant_id>/edit/", views.edit_grant, name="edit_grant"),
    path("grants/<int:grant_id>/delete/", views.delete_grant, name="delete_grant"),
    path("vests/add/", views.add_vest, name="add_vest"),
    path("vests/<int:vest_id>/edit/", views.edit_vest, name="edit_vest"),
    path("vests/<int:vest_id>/delete/", views.delete_vest, name="delete_vest"),
    path("vests/", views.vest_list, name="vest_list"),
    path("sales/add/", views.add_sale, name="add_sale"),
    path("sales/<int:sale_id>/edit/", views.edit_sale, name="edit_sale"),
    path("sales/<int:sale_id>/delete/", views.delete_sale, name="delete_sale"),
    path("sales/", views.sale_list, name="sale_list"),
    path("brokers/", views.broker_management, name="broker_management"),
    path("brokers/<int:broker_id>/grant-ids/", views.broker_grant_ids, name="broker_grant_ids"),
    path("brokers/add/", views.add_broker, name="add_broker"),
    path("brokers/<int:broker_id>/edit/", views.edit_broker, name="edit_broker"),
    path("brokers/<int:broker_id>/delete/", views.delete_broker, name="delete_broker"),
    path("imports/etrade/", views.import_etrade_history, name="import_etrade_history"),
    path("rates/add/", views.add_rate, name="add_rate"),
    path("rates/", views.rate_list, name="rate_list"),
    path("rates/fetch/", views.fetch_hmrc_rate, name="fetch_hmrc_rate"),
    path("rates/fetch-wise/", views.fetch_wise_rate, name="fetch_wise_rate"),
    path("rates/<int:rate_id>/edit/", views.edit_rate, name="edit_rate"),
    path("rates/<int:rate_id>/delete/", views.delete_rate, name="delete_rate"),
    path("prices/", views.price_list, name="price_list"),
    path("prices/add/", views.add_price, name="add_price"),
    path("prices/<int:price_id>/edit/", views.edit_price, name="edit_price"),
    path("prices/<int:price_id>/delete/", views.delete_price, name="delete_price"),
    path("securities/", views.security_list, name="security_list"),
    path("securities/add/", views.add_security, name="add_security"),
    path("securities/<int:security_id>/edit/", views.edit_security, name="edit_security"),
    path("securities/<int:security_id>/delete/", views.delete_security, name="delete_security"),
    path("section-104/", views.section_104_working_paper, name="section_104_working_paper"),
    path("access/", views.access_management, name="access_management"),
]
if settings.SCIM_ENABLED:
    urlpatterns.append(path("scim/v2/", include(("django_scim.urls", "scim"), namespace="scim")))
