"""Save full-page screenshots of pages on the local development site.

Usage:
    uv run python scripts/screenshots.py OUT_DIR URL [URL ...] [--session SESSION_ID] [--width 1440]

OUT_DIR is created if needed. Files are numbered in the order the URLs are given.
--session takes the value of the Django session cookie, so pages behind sign-in can be
captured. Stage 1 adds `manage.py dev_login <email>`, which prints one (development only).

In a cloud session Chromium is already installed. Never run `playwright install`.
"""

import argparse
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

CLOUD_CHROMIUM = "/opt/pw-browsers/chromium"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir")
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--session", default="")
    parser.add_argument("--width", type=int, default=1440)
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    launch = {}
    if os.path.exists(CLOUD_CHROMIUM):
        launch["executable_path"] = CLOUD_CHROMIUM

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        context = browser.new_context(viewport={"width": args.width, "height": 900})
        if args.session:
            host = urlparse(args.urls[0]).hostname or "127.0.0.1"
            context.add_cookies(
                [
                    {
                        "name": "sessionid",
                        "value": args.session,
                        "domain": host,
                        "path": "/",
                    }
                ]
            )
        page = context.new_page()
        for number, url in enumerate(args.urls, 1):
            page.goto(url, wait_until="networkidle")
            target = out / f"{number:02d}.png"
            page.screenshot(path=str(target), full_page=True)
            print(f"saved {target}  {page.title()}")
        browser.close()


if __name__ == "__main__":
    main()
