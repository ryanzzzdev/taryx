"""Counterparty callback ingress — the only inbound edge of
taryx-market/1. Bearer token + version header are checked before any
state moves; malformed payloads are parked as exceptions and rejected.
"""

import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from taryx.core.market.models import MarketException
from taryx.core.market.services import apply_callback


@csrf_exempt  # machine-to-machine bearer auth, not a browser session
@require_POST
def transfer_callback(request):
    if request.headers.get("taryx-market-version") != "1":
        return JsonResponse({"error": "version_mismatch"}, status=400)
    if request.headers.get("Authorization") != f"Bearer {settings.MARKET_CALLBACK_TOKEN}":
        return JsonResponse({"error": "unauthorised"}, status=401)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        MarketException.objects.create(
            reason="malformed", raw=request.body[:2000].decode("utf-8", "replace")
        )
        return JsonResponse({"error": "malformed"}, status=400)
    if not isinstance(payload, dict):
        MarketException.objects.create(
            reason="malformed", raw=request.body[:2000].decode("utf-8", "replace")
        )
        return JsonResponse({"error": "malformed"}, status=400)
    try:
        result = apply_callback(payload)
    except ValueError as exc:
        MarketException.objects.create(reason="malformed", raw=json.dumps(payload)[:2000])
        return JsonResponse({"error": "malformed", "detail": str(exc)}, status=400)
    return JsonResponse(result)
