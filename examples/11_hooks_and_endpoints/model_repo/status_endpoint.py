"""Custom endpoint — GET /status returns a quick overview."""

methods = ["GET"]


def handler(request, server):
    """Return a quick status overview of the server."""
    models = server.registry.list_loaded()
    return {
        "server": "light-server",
        "loaded_models_count": len(models),
        "loaded_models": models,
    }
