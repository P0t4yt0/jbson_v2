from security.models import ActivityLog

def log_system_activity(user, action, description):
    """
    Tawagin ito tuwing may nangyayaring transaction o report generation.
    """
    if user.is_authenticated:
        ActivityLog.objects.create(
            user=user,
            action=action,
            description=description
        )