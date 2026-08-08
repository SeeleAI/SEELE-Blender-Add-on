from urllib.parse import urlparse


def normalize_origin(value):
    value = (value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return ""
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return ""
    return f"{parsed.scheme}://{parsed.hostname.lower()}{port}"


def allowed_origins(production_origin, development_origins="", development_enabled=False):
    values = [production_origin]
    if development_enabled:
        values.extend(development_origins.replace("\n", ",").split(","))
    return {origin for origin in (normalize_origin(value) for value in values) if origin}


def is_origin_allowed(origin, allowed):
    return normalize_origin(origin) in allowed
