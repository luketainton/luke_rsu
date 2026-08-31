from django.contrib import admin

from .models import FxRate, Grant, Sale, User, Vest, Workspace, WorkspaceMembership

admin.site.register([User, Workspace, WorkspaceMembership, Grant, Vest, Sale, FxRate])
