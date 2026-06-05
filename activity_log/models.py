
def log_system_activity(user, action='report_generated', description="", **kwargs):
    """
    Utility function to save system activities based on the ActivityLog model.
    """
    if 'message' in kwargs and not description:
        description = kwargs.pop('message')

    valid_actions = [choice[0] for choice in ActivityLog.ACTION_CHOICES]
    if action not in valid_actions:
        description = f"{action} - {description}".strip(" -")
        action = 'report_generated' 

    
    if user.is_authenticated:
        ActivityLog.objects.create(
            user=user,
            action=action,               
            description=description,     
            source_table=kwargs.get('source_table', ''),
            source_id=kwargs.get('source_id', ''),
            ip_address=kwargs.get('ip_address')
        )