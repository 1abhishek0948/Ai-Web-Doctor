"""URL validation and SSRF protection for the scanner.

Users can submit arbitrary URLs, so every target (and every redirect hop) must
be validated before a headless browser is pointed at it. This module:

* only allows ``http`` and ``https`` schemes,
* rejects private / loopback / link-local / reserved IP ranges,
* rejects known internal and metadata hostnames,
* resolves DNS and checks every resolved address,
* validates redirect targets as well as the original URL.

DNS rebinding cannot be fully prevented without pinning connections to a
resolved IP, but validating each hop immediately before navigation narrows the
attack surface for this MVP. See the project README for the deployment notes.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = ("http", "https")

# Hostnames that are never safe to scan, regardless of what they resolve to.
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "broadcasthost",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
        "metadata",
    }
)

# Suffixes commonly used for internal-only hostnames.
_BLOCKED_SUFFIXES = (".local", ".internal", ".home.arpa", ".lan", ".corp")

# Cloud metadata endpoints are link-local addresses (169.254.169.254) and are
# therefore already rejected by the IP checks; this list documents the intent.
_CLOUD_METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",  # AWS / GCP
        "169.254.170.2",  # AWS ECS
        "100.100.100.200",  # Alibaba Cloud
        "metadata.azure.internal",  # Azure
    }
)


class ScanSecurityError(Exception):
    """Raised when a target URL is unsafe or malformed."""


@dataclass(frozen=True)
class ValidatedURL:
    """A normalized URL that passed validation, plus its host."""

    url: str
    scheme: str
    hostname: str


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def is_blocked_ip(ip_str: str) -> bool:
    """Return True if the given IP string must never be scanned."""
    try:
        ip = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        # Not a valid literal IP; allow hostname resolution to decide.
        return False

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _blocked_hostname(hostname: str) -> bool:
    lowered = hostname.lower().rstrip(".")
    if lowered in BLOCKED_HOSTNAMES or lowered in _CLOUD_METADATA_HOSTS:
        return True
    if _is_ip_address(lowered):
        return is_blocked_ip(lowered)
    return lowered.endswith(_BLOCKED_SUFFIXES)


def _resolve_hostname(hostname: str) -> list[str]:
    """Resolve a hostname to a list of IP strings, raising on failure."""
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ScanSecurityError(f"Could not resolve host '{hostname}'.") from exc

    addresses: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        raise ScanSecurityError(f"Host '{hostname}' did not resolve to any address.")
    return addresses


def _validate_host(hostname: str) -> None:
    """Validate a hostname: blocked names plus DNS resolution and IP ranges."""
    if not hostname:
        raise ScanSecurityError("The URL does not contain a hostname.")

    if _blocked_hostname(hostname):
        raise ScanSecurityError(f"Host '{hostname}' is not allowed.")

    resolved = _resolve_hostname(hostname)
    for ip in resolved:
        if is_blocked_ip(ip):
            raise ScanSecurityError(
                f"Host '{hostname}' resolves to a private or restricted address ({ip})."
            )
    logger.info("Validated host '%s' -> %s", hostname, resolved)


def normalize_url(raw_url: str) -> str:
    """Normalize a user-supplied URL string.

    Bare domains get an ``https://`` prefix. A trailing slash is preserved but
    nothing else is rewritten.
    """
    candidate = (raw_url or "").strip()
    if not candidate:
        raise ScanSecurityError("Please enter a URL to scan.")

    if not any(candidate.lower().startswith(scheme) for scheme in ALLOWED_SCHEMES):
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ScanSecurityError(
            f"Only http:// and https:// URLs are supported (got '{parsed.scheme}')."
        )
    if not parsed.hostname:
        raise ScanSecurityError("The URL does not contain a valid hostname.")

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def validate_url(raw_url: str) -> ValidatedURL:
    """Validate a target URL and return a normalized, safe form.

    Raises :class:`ScanSecurityError` for unsafe or unresolvable targets.
    """
    url = normalize_url(raw_url)
    parsed = urlparse(url)
    _validate_host(parsed.hostname or "")
    return ValidatedURL(url=url, scheme=parsed.scheme, hostname=parsed.hostname or "")


def validate_redirect_url(url: str) -> None:
    """Validate a redirect target discovered during navigation."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ScanSecurityError(
            f"Redirect to unsupported scheme '{parsed.scheme}' was blocked."
        )
    if not parsed.hostname:
        raise ScanSecurityError("Redirect target has no hostname.")
    if _blocked_hostname(parsed.hostname):
        raise ScanSecurityError(
            f"Redirect to restricted host '{parsed.hostname}' was blocked."
        )
    resolved = _resolve_hostname(parsed.hostname)
    for ip in resolved:
        if is_blocked_ip(ip):
            raise ScanSecurityError(
                f"Redirect resolves to a private or restricted address ({ip})."
            )
