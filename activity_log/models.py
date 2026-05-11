
def log_system_activity(user, action='report_generated', description="", **kwargs):
    """
    Utility function to save system activities based on the ActivityLog model.
    """
    # 1. Catch 'message' if your views are still passing it instead of 'description'
    if 'message' in kwargs and not description:
        description = kwargs.pop('message')

    # 2. Handle invalid actions. If a view passes action="Viewed Sales Report" 
    # (which isn't in your ACTION_CHOICES), we move that text to description 
    # and use a default valid action to prevent database/admin display errors.
    valid_actions = [choice[0] for choice in ActivityLog.ACTION_CHOICES]
    if action not in valid_actions:
        description = f"{action} - {description}".strip(" -")
        action = 'report_generated' # Fallback valid choice

    # 3. Save to database using the exact field names from your model
    if user.is_authenticated:
        ActivityLog.objects.create(
            user=user,
            action=action,               # Must be one of your ACTION_CHOICES
            description=description,     # The detailed, human-readable text
            source_table=kwargs.get('source_table', ''),
            source_id=kwargs.get('source_id', ''),
            ip_address=kwargs.get('ip_address')
        )