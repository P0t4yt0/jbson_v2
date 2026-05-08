from django.shortcuts import render
from django.core.paginator import Paginator
from auditlog.models import LogEntry
from django.db.models import Q

# WAG KALIMUTANG I-IMPORT ANG ACTIVITYLOG MODEL MO!
# I-adjust ang import path kung nasa ibang folder/app ito.
from security.models import ActivityLog 

def activity_logs_view(request):
    # 1. KUNIN ANG DATA MULA SA DALAWANG TABLES
    audit_logs = LogEntry.objects.all()
    custom_logs = ActivityLog.objects.all()

    # 2. SEARCH FILTER LOGIC
    search_query = request.GET.get('search', '')
    if search_query:
        audit_logs = audit_logs.filter(
            Q(actor__username__icontains=search_query) | 
            Q(object_repr__icontains=search_query)
        )
        custom_logs = custom_logs.filter(
            Q(user__username__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # 3. ACTION FILTER LOGIC (Dropdown)
    action_filter = request.GET.get('action', '')
    if action_filter:
        # Kung numbers (0, 1, 2), para ito sa AuditLog (ADD, EDIT, DELETE)
        if action_filter in ['0', '1', '2']:
            audit_logs = audit_logs.filter(action=action_filter)
            custom_logs = custom_logs.none() # Wag isama ang custom
        # Kung text (LOGIN, LOGOUT, USER_CREATED), para ito sa Custom Logs
        else:
            custom_logs = custom_logs.filter(action=action_filter)
            audit_logs = audit_logs.none() # Wag isama ang audit

    # 4. PAGSAMAHIN AT I-FORMAT (Unified List)
    unified_logs = []
    
    # Diksyonaryo para i-translate ang mga letters (Pwede mong baguhin kung may iba kang gusto)
    abc_mapping = {
        'A': 'Always in Stock',
        'B': 'Regular Check',
        'C': 'Bulk Order',
        'U': 'Unclassified',
        'None': 'Unclassified'
    }

    # Ipasok ang AuditLogs
    for al in audit_logs:
        # Kopyahin ang changes para pwede nating i-edit nang hindi nasisira ang database
        changes = dict(getattr(al, 'changes_dict', {}) or {})
        
        # Kung napansin ng system na ABC classification ang inedit, ita-translate niya!
        if 'abc_classification' in changes:
            old_val = str(changes['abc_classification'][0])
            new_val = str(changes['abc_classification'][1])
            
            changes['abc_classification'] = [
                abc_mapping.get(old_val, old_val),
                abc_mapping.get(new_val, new_val)
            ]

        unified_logs.append({
            'id': al.id,
            'actor': al.actor,
            'action': al.action,
            'object_repr': al.object_repr,
            'changes_dict': changes,  # <--- Ipasa ang na-translate na changes!
            'content_object': getattr(al, 'content_object', None),
            'object_id': getattr(al, 'object_id', getattr(al, 'object_pk', '')), 
            'model_name': getattr(al.content_type, 'name', 'record') if al.content_type else 'record',
            'timestamp': al.timestamp,
        })
        
    # Ipasok ang Custom Logs (at i-match ang keys sa kailangan ng HTML mo)
    for cl in custom_logs:
        unified_logs.append({
            'id': cl.id,
            'actor': cl.user, # Ginawang 'actor' para parehas sila ng tawag sa HTML
            'action': cl.action,
            'description': cl.description,
            'timestamp': cl.timestamp,
            # Blank defaults para hindi mag-error ang HTML
            'object_repr': '',
            'changes_dict': {},
            'content_object': None,
            'object_id': '',
        })
        
    # 5. I-SORT BY DATE & TIME (Pinakabago sa taas)
    unified_logs.sort(key=lambda x: x['timestamp'], reverse=True)

    # 6. PAGINATION
    rows_per_page = request.GET.get('rows', 10)
    paginator = Paginator(unified_logs, int(rows_per_page))
    page_number = request.GET.get('page', 1)
    logs = paginator.get_page(page_number)

    context = {
        'logs': logs,
        'search_query': search_query,
        'action_filter': action_filter,
        'rows': int(rows_per_page),
    }
    
    return render(request, 'dashboard/activity_logs.html', context)