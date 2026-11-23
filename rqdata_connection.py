"""Shared RQData initialization and credential-safe diagnostic messages."""
from __future__ import annotations

import os
import re
from urllib.parse import unquote


def connection_parameters(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    if not value:
        raise ValueError("RQData credential is empty")
    if any(char.isspace() for char in value):
        raise ValueError("RQData credential contains spaces or line breaks; paste one complete line")
    if "://" not in value:
        return {"username": "license", "password": value,
                "addr": ("rqdatad-pro.ricequant.com", 16011)}
    match = re.fullmatch(r"(?:rqdata|rqdatac|tcp)://([^:]+):(.+)@([^:/?#]+):(\d+)", value)
    if not match:
        raise ValueError("Invalid RQData connection format; use only the License Key or rqdata://license:KEY@HOST:PORT")
    username, password, hostname, port = match.groups()
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("RQData connection port is invalid")
    return {"username": unquote(username), "password": unquote(password),
            "addr": (hostname, port)}


def credential_value():
    # Preserve the SDK's RQDATAC2_CONF precedence for existing local RQSDK setups.
    return os.environ.get("RQDATA_LICENSE") or os.environ.get("RQDATAC2_CONF") or os.environ.get("RQDATAC_CONF") or ""


def initialize_rqdata():
    from retired_provider import unavailable
    unavailable()


def safe_error(error):
    message = str(error)
    for name in ("RQDATA_LICENSE", "RQDATAC_CONF", "RQDATAC2_CONF", "AIDO_API_KEY"):
        value = os.environ.get(name, "")
        candidates = [value, value.strip()]
        if value and name != "AIDO_API_KEY":
            try:
                candidates.append(connection_parameters(value)["password"])
            except ValueError:
                pass
        for secret in sorted(set(candidates), key=len, reverse=True):
            if secret:
                message = message.replace(secret, "[redacted]")
    message = re.sub(r"(?:rqdata|rqdatac|tcp)://[^\s]+", "[redacted connection]", message)
    return f"{type(error).__name__}: {message[:800]}"
