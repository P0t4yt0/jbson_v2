from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator

from .models import Notification
from inventory.models import PurchaseOrder
from django.views.decorators.http import require_POST

def live_notifications_api(request):
    """Returns unread notifications as JSON for the background polling."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    # --- SMART P.O. DELIVERY DATE CHECKER ---
    if getattr(request.user, "role", "employee") == "admin":
        today = timezone.now().date()
        User = get_user_model()
        admins = User.objects.filter(role='Admin', is_active=True)

        # A. Check for Deliveries Expected TODAY
        deliveries_today = PurchaseOrder.objects.filter(status='pending', expected_delivery=today)
        for po in deliveries_today:
            for admin_user in admins:
                Notification.objects.get_or_create(
                    user=admin_user,
                    notification_type='po_alert',
                    source_id=f"po_today_{po.id}", 
                    defaults={
                        'priority': 'medium',
                        'title': 'Delivery Expected Today',
                        'message': f"PO {po.po_number} from {po.supplier.name} is scheduled to arrive today.",
                        'action_url': reverse('inventory:create_po')
                    }
                )

        # B. Check for OVERDUE Deliveries
        overdue_deliveries = PurchaseOrder.objects.filter(status='pending', expected_delivery__lt=today)
        for po in overdue_deliveries:
            for admin_user in admins:
                Notification.objects.get_or_create(
                    user=admin_user,
                    notification_type='po_alert',
                    source_id=f"po_overdue_{po.id}",
                    defaults={
                        'priority': 'high',
                        'title': 'Overdue Delivery Alert',
                        'message': f"PO {po.po_number} from {po.supplier.name} was due on {po.expected_delivery.strftime('%b %d')}. Please mark as received if it arrived.",
                        'action_url': reverse('inventory:create_po')
                    }
                )

    # --- FETCH NOTIFICATIONS --- (replace from this line down to the return)
    notifications_qs = Notification.objects.filter(
        Q(user=request.user) | Q(user__isnull=True)
    ).order_by('is_read', '-date_created')[:10]  # unread first, then read, max 10

    notifications_data = []
    for notif in notifications_qs:
        notifications_data.append({
            'id': notif.id,
            'title': notif.title,
            'message': notif.message,
            'priority': notif.priority,
            'type': notif.notification_type,
            'time': timezone.localtime(notif.date_created).strftime("%I:%M %p"),
            'action_url': notif.action_url if notif.action_url else '#',
            'is_read': notif.is_read,   # <-- THIS is the key addition
        })

    total_unread = Notification.objects.filter(
        Q(user=request.user) | Q(user__isnull=True),
        is_read=False
    ).count()

    return JsonResponse({
        'unread_count': total_unread,
        'notifications': notifications_data
    })



@require_POST
def mark_all_read_api(request):
    """Marks all notifications as read when 'Clear All' is clicked."""
    if request.method == 'POST' and request.user.is_authenticated:
        Notification.objects.filter(
            Q(user=request.user) | Q(user__isnull=True),
            is_read=False
        ).update(is_read=True, date_read=timezone.now())
        return JsonResponse({'status': 'success'})
    return JsonResponse({'error': 'Invalid request'}, status=400)


@require_POST
def mark_single_read_api(request, notif_id):
    """Marks a single notification as read via AJAX without redirecting."""
    if request.method == 'POST' and request.user.is_authenticated:
        try:
            notif = Notification.objects.get(id=notif_id, is_read=False)
            if notif.user == request.user or notif.user is None:
                notif.is_read = True
                notif.date_read = timezone.now()
                notif.save(update_fields=['is_read', 'date_read'])
                
                # NEW: Calculate the remaining unread notifications to send back
                remaining_count = Notification.objects.filter(
                    Q(user=request.user) | Q(user__isnull=True),
                    is_read=False
                ).count()
                
                return JsonResponse({'status': 'success', 'unread_count': remaining_count})
        except Notification.DoesNotExist:
            pass
            
    return JsonResponse({'error': 'Invalid request'}, status=400)


def mark_single_read_and_redirect(request, notif_id):
    """Marks one notification as read, then sends the user to the action_url."""
    notif = get_object_or_404(Notification, id=notif_id)
    
    if not notif.is_read:
        notif.is_read = True
        notif.date_read = timezone.now()
        notif.save(update_fields=['is_read', 'date_read'])
        
    if notif.action_url:
        return redirect(notif.action_url)
    return redirect('admin_dashboard')

@login_required
def notification_history_view(request):
    """Displays a full paginated page of the user's notification history."""
    notifs_list = Notification.objects.filter(
        Q(user=request.user) | Q(user__isnull=True)
    ).order_by('-date_created')

    paginator = Paginator(notifs_list, 20) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'notifications/history.html', {'page_obj': page_obj})

def delete_notification_api(request, notif_id):
    if request.method == 'POST':
        notif = get_object_or_404(Notification, id=notif_id)
        notif.delete()
        
        # FIXED - only count current user's unread
        from django.db.models import Q
        unread_count = Notification.objects.filter(
            Q(user=request.user) | Q(user__isnull=True),
            is_read=False
        ).count()
        
        return JsonResponse({
            'status': 'success',
            'unread_count': unread_count
        })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)