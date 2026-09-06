from django.contrib import admin

from .models import (
    Broker,
    FxRate,
    Grant,
    PoolAdjustment,
    Purchase,
    Sale,
    Section104OpeningBalance,
    Section104Snapshot,
    Security,
    StockPrice,
    User,
    Vest,
    Workspace,
    WorkspaceMembership,
)

admin.site.register(
    [
        User,
        Workspace,
        WorkspaceMembership,
        Broker,
        Security,
        Grant,
        Vest,
        Sale,
        Purchase,
        PoolAdjustment,
        FxRate,
        StockPrice,
        Section104OpeningBalance,
        Section104Snapshot,
    ]
)
