"""Custom global health endpoint — overrides the default /health."""

import time

START_TIME = time.time()


def handler(request, server):
    """Return server-wide health with uptime and loaded model count."""
    loaded = server.registry.list_loaded()
    return {
        "status": "ok",
        "custom_health": True,
        "uptime_seconds": round(time.time() - START_TIME, 2),
        "loaded_models": len(loaded),
        "models": loaded,
    }
