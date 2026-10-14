"""gunicorn settings for the web process. Values can be changed with environment variables."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
timeout = int(os.environ.get("WEB_TIMEOUT", "60"))
# Restart each worker now and then, so a slow leak never builds up.
max_requests = 1000
max_requests_jitter = 100
# No access log: addresses can hold tokens, and the host's router logs requests anyway.
accesslog = None
errorlog = "-"
# The host's proxy ends TLS; Django reads X-Forwarded-Proto (SECURE_PROXY_SSL_HEADER).
forwarded_allow_ips = "*"
# Body size is capped by RequestSizeLimitMiddleware; headers are capped here.
limit_request_field_size = 8190
