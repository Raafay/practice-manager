from django.core.paginator import Page, Paginator

DEFAULT_PER_PAGE = 50


def paginate(request, queryset, per_page: int = DEFAULT_PER_PAGE) -> Page:
    """Return the requested page. A bad or out-of-range page number gives the nearest page."""
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get("page"))


def page_query(request, number: int) -> str:
    """The current query string with only the page number changed."""
    params = request.GET.copy()
    params["page"] = number
    return params.urlencode()
