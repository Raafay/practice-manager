from . import services


def overview_context(user) -> dict:
    if not user.can("clients.status"):
        return {}
    return {"credit_drops": services.recent_drops(5), "credit_panel": True}
