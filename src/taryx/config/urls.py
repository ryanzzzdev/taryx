from django.db import connection
from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import ensure_csrf_cookie
from graphene_django.views import GraphQLView

from taryx.interfaces.callbacks import transfer_callback
from taryx.interfaces.metrics import metrics


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz", healthz),
    path("metrics", metrics),
    # Session-authenticated, CSRF-enforced (decision 004). ensure_csrf_cookie
    # lets GET/GraphiQL responses carry the csrftoken cookie the portal
    # echoes back as X-CSRFToken on mutations.
    path("graphql", ensure_csrf_cookie(GraphQLView.as_view(graphiql=True))),
    # Synthetic taryx-market/1 inbound edge (decision 005).
    path("callbacks/transfers", transfer_callback),
]
