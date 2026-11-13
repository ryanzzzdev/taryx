"""HTTP middleware — request-id correlation for API and ingress logs."""

from taryx.diagnostics import bind_context, new_request_id

_HEADER = "HTTP_X_REQUEST_ID"


class RequestIdMiddleware:
    """Honour an inbound `X-Request-ID` (bounded length) or mint one,
    bind it to the log context for the request, and echo it on the
    response so client, API and worker logs share a join key."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = (request.META.get(_HEADER) or "")[:64] or new_request_id()
        request.request_id = request_id
        with bind_context(request_id=request_id):
            response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response
