from .models import EmployeeProfile

def admin_notifications(request):
    # Pinalitan natin ang is_superuser ng is_admin para mag-match sa User model mo
    if request.user.is_authenticated and request.user.is_admin: 
        
        pending_resets = EmployeeProfile.objects.filter(reset_requested=True)
        count = pending_resets.count()
        
        return {
            'pending_resets': pending_resets,
            'pending_reset_count': count
        }
    
    # Kung hindi admin, walang ibabalik
    return {}