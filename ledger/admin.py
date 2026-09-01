from django.contrib import admin

from .models import (
    Broker,
    FxRate,
    Grant,
    Sale,
    Security,
    StockPrice,
    User,
    Vest,
    Workspace,
    WorkspaceMembership,
)

admin.site.register(
    [User, Workspace, WorkspaceMembership, Broker, Security, Grant, Vest, Sale, FxRate, StockPrice]
)
