def get_username(request, credentials) -> str:
    """The account name django-axes counts failures against: the email, lower case."""
    credentials = credentials or {}
    value = credentials.get("email") or credentials.get("username") or credentials.get("login")
    if not value and request is not None:
        value = request.POST.get("login", "")
    return str(value or "").strip().lower()
