from django.shortcuts import render
from django.core.paginator import Paginator
from auditlog.models import LogEntry
from django.db.models import Q
import re
 
from security.models import ActivityLog 

def activity_logs_view(request):
    audit_logs = LogEntry.objects.all()
    custom_logs = ActivityLog.objects.all()
    role_filter = request.GET.get('role', '')
    # SEARCH FILTER LOGIC
    search_query = request.GET.get('search', '').strip()
    if search_query:
        audit_q = Q(actor__username__icontains=search_query) | Q(object_repr__icontains=search_query)
        custom_q = Q(user__username__icontains=search_query) | Q(description__icontains=search_query)

        numbers_in_query = re.findall(r'\d+', search_query)
        
        if numbers_in_query:
            search_id = int(numbers_in_query[-1]) 
            search_upper = search_query.upper()

            if search_upper.startswith('AUD'):
                audit_q |= Q(id=search_id)
            elif search_upper.startswith(('ACT', 'TRX', 'SYS', 'AUTH')):
                custom_q |= Q(id=search_id)
            else:
                audit_q |= Q(id=search_id)
                custom_q |= Q(id=search_id)

        audit_logs = audit_logs.filter(audit_q)
        custom_logs = custom_logs.filter(custom_q)

        audit_logs = audit_logs.filter(audit_q)
        custom_logs = custom_logs.filter(custom_q)

    action_filter = request.GET.get('action', '')
    if action_filter:
        if action_filter in ['0', '1', '2']:
            audit_logs = audit_logs.filter(action=action_filter)
            custom_logs = custom_logs.none() 
        else:
            custom_logs = custom_logs.filter(action=action_filter)
            audit_logs = audit_logs.none()

    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    if start_date:
        start_datetime = f"{start_date} 00:00:00"
        audit_logs = audit_logs.filter(timestamp__gte=start_datetime)
        custom_logs = custom_logs.filter(timestamp__gte=start_datetime)
        
    if end_date:
        end_datetime = f"{end_date} 23:59:59"
        audit_logs = audit_logs.filter(timestamp__lte=end_datetime)
        custom_logs = custom_logs.filter(timestamp__lte=end_datetime)

    unified_logs = []
    
    abc_mapping = {
        'A': 'Always in Stock',
        'B': 'Regular Check',
        'C': 'Bulk Order',
        'U': 'Unclassified',
        'None': 'Unclassified'
    }

    for al in audit_logs:
        changes = dict(getattr(al, 'changes_dict', {}) or {})

        date_str = al.timestamp.strftime('%y%m%d')

        unified_logs.append({
            'id': f"AUD-{date_str}-{al.id:04d}",  
            'actor': al.actor,
            'action': al.action,
            'object_repr': al.object_repr,
            'changes_dict': changes,
            'content_object': getattr(al, 'content_object', None),
            'object_id': getattr(al, 'object_id', getattr(al, 'object_pk', '')), 
            'model_name': getattr(al.content_type, 'name', 'record') if al.content_type else 'record',
            'timestamp': al.timestamp,
        })
        
    for cl in custom_logs:
        action_type = str(cl.action).upper()
        date_str = cl.timestamp.strftime('%y%m%d')
        
        if action_type in ['POS TRANSACTION', 'SALES RETURN', 'CREATE PO', 'RECEIVE PO']:
            prefix = "TRX"
        elif action_type in ['LOGIN', 'LOGOUT', 'USER_CREATED', 'USER_MODIFIED']:
            prefix = "AUTH"
        elif action_type in ['GENERATE REPORT', 'ABC ANALYSIS', 'BULK DELETE']:
            prefix = "SYS"
        else:
            prefix = "ACT"

        unified_logs.append({
            'id': f"{prefix}-{date_str}-{cl.id:04d}", 
            'actor': cl.user,
            'action': cl.action,
            'description': cl.description,
            'timestamp': cl.timestamp,
            'object_repr': '',
            'changes_dict': {},
            'content_object': None,
            'object_id': '',
        })
    # FILTER BY ROLE
    if role_filter == 'Admin':
        audit_logs = audit_logs.filter(actor__is_superuser=True)
        custom_logs = custom_logs.filter(user__is_superuser=True)
    elif role_filter == 'Employee':
        audit_logs = audit_logs.filter(actor__is_superuser=False)
        custom_logs = custom_logs.filter(user__is_superuser=False)
        
    unified_logs.sort(key=lambda x: x['timestamp'], reverse=True)

    # PAGINATION
    rows_per_page = request.GET.get('rows', 10)
    paginator = Paginator(unified_logs, int(rows_per_page))
    page_number = request.GET.get('page', 1)
    logs = paginator.get_page(page_number)

    context = {
        'logs': logs,
        'search_query': search_query,
        'action_filter': action_filter,
        'role_filter': role_filter,    
        'start_date': start_date, 
        'end_date': end_date, 
        'rows': int(rows_per_page),
    }
    
    return render(request, 'dashboard/activity_logs.html', context)