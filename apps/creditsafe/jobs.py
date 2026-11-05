from datetime import time

from apps.jobs.registry import Daily, register

from . import services


@register(
    "creditsafe_alerts",
    "Credit rating alerts",
    Daily(time(7, 0)),
    description="Reads Creditsafe monitoring alerts and fetches a new report only for the "
    "companies they name. Does nothing until Creditsafe is set up.",
)
def creditsafe_alerts(run):
    return services.run_alerts()
