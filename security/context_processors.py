from .models import EmployeeProfile

def admin_notifications(request):
    if request.user.is_authenticated and request.user.is_admin: 
        pending_resets = EmployeeProfile.objects.filter(reset_requested=True)
        count = pending_resets.count()
        return {
            'pending_resets': pending_resets,
            'pending_reset_count': count
        }
    return {}