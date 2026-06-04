from django.contrib import admin
from .models import (
    User, UserData, NotificationData,
    WearableDevice, HeartRateSample, ActivitySummary, EMA, JITAILog,
)

admin.site.register(User)
admin.site.register(UserData)
admin.site.register(NotificationData)
admin.site.register(WearableDevice)
admin.site.register(HeartRateSample)
admin.site.register(ActivitySummary)
admin.site.register(EMA)
admin.site.register(JITAILog)