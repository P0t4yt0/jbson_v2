from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from .models import Notification
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

def live_notifications_api(request):
    """Returns unread notifications as JSON for the background polling."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    # 1. Fetch unread notifications for THIS user OR broadcast notifications (user is None)
    unread_qs = Notification.objects.filter(
        Q(user=request.user) | Q(user__isnull=True),
        is_read=False
    ).order_by('-date_created')[:5] # Get latest 5
    
    notifications_data = []
    for notif in unread_qs:
        notifications_data.append({
            'id': notif.id,
            'title': notif.title,
            'message': notif.message,
            'priority': notif.priority, # 'critical', 'high', 'medium', 'low'
            'type': notif.notification_type,
            'time': notif.date_created.strftime("%I:%M %p")
        })

    # 2. Get total count of unread
    total_unread = Notification.objects.filter(
        Q(user=request.user) | Q(user__isnull=True),
        is_read=False
    ).count()

    return JsonResponse({
        'unread_count': total_unread,
        'notifications': notifications_data
    })

@csrf_exempt # Allows our JavaScript to ping this safely
def mark_all_read_api(request):
    if request.user.is_authenticated and request.method == 'POST':
        # Find all unread alerts for this user (and global broadcasts)
        unread = Notification.objects.filter(
            Q(user=request.user) | Q(user__isnull=True),
            is_read=False
        )
        
        # Update them all to True and stamp the current time!
        unread.update(is_read=True, date_read=timezone.now())
        
        return JsonResponse({'status': 'success'})
    return JsonResponse({'error': 'Invalid request'}, status=400)
# Create your views here.
