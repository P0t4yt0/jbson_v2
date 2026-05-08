from django.shortcuts import render
from django.core.paginator import Paginator
from auditlog.models import LogEntry
from django.db.models import Q

def activity_logs_view(request):
    logs_list = LogEntry.objects.all().order_by('-timestamp')

    search_query = request.GET.get('search', '')
    if search_query:
        logs_list = logs_list.filter(
            Q(actor__username__icontains=search_query) | 
            Q(object_repr__icontains=search_query)
        )

    action_filter = request.GET.get('action', '')
    if action_filter:
        logs_list = logs_list.filter(action=action_filter)

    rows_per_page = request.GET.get('rows', 10)
    paginator = Paginator(logs_list, int(rows_per_page))
    
    page_number = request.GET.get('page', 1)
    logs = paginator.get_page(page_number)

    context = {
        'logs': logs,
        'search_query': search_query,
        'action_filter': action_filter,
        'rows': int(rows_per_page),
    }
    
    # Siguraduhing tumutugma ito sa HTML file mo!
    return render(request, 'dashboard/activity_logs.html', context)