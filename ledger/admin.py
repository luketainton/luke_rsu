from django.contrib import admin

from .models import (
    Broker,
    FxRate,
    Grant,
    Sale,
    StockPrice,
    User,
    Vest,
    Workspace,
    WorkspaceMembership,
)

admin.site.register(
    [User, Workspace, WorkspaceMembership, Broker, Grant, Vest, Sale, FxRate, StockPrice]
)
