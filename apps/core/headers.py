"""What the security headers must be (spec 01 section 11). Used by a test against the
production settings and by `manage.py check_headers <address>` against the live site."""

EXPECTED = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}
CSP_PARTS = ("default-src 'self'", "script-src 'self'", "frame-ancestors 'none'")


def header_problems(headers, set_cookies: list[str]) -> list[str]:
    """headers: a mapping with case-insensitive lookup. set_cookies: Set-Cookie lines."""
    problems = []
    for name, wanted in EXPECTED.items():
        value = headers.get(name) or ""
        if wanted not in value:
            problems.append(f"{name} should contain {wanted!r}, got {value!r}.")
    csp = headers.get("Content-Security-Policy") or ""
    for part in CSP_PARTS:
        if part not in csp:
            problems.append(f"Content-Security-Policy should contain {part!r}.")
    script_src = csp.split("script-src", 1)[1].split(";", 1)[0] if "script-src" in csp else ""
    if "unsafe" in script_src:
        problems.append("Content-Security-Policy allows unsafe scripts.")
    for line in set_cookies:
        name = line.split("=", 1)[0].strip()
        lower = line.lower()
        if "; secure" not in lower:
            problems.append(f"Cookie {name} is not marked Secure.")
        if "samesite=lax" not in lower and "samesite=strict" not in lower:
            problems.append(f"Cookie {name} is not SameSite Lax.")
        if name in ("sessionid", "csrftoken") and "httponly" not in lower:
            problems.append(f"Cookie {name} is not HttpOnly.")
    return problems
