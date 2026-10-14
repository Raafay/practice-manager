"""Check the live site's security headers and cookies: manage.py check_headers https://..."""

import urllib.request

from django.core.management.base import BaseCommand, CommandError

from apps.core.headers import header_problems


class Command(BaseCommand):
    help = "Fetch the sign-in page of a live address and check its security headers."

    def add_arguments(self, parser):
        parser.add_argument(
            "address", help="The site's address, for example https://pm.example.co.uk"
        )

    def handle(self, *args, address, **options):
        if not address.startswith("https://"):
            raise CommandError("Give the https:// address.")
        url = address.rstrip("/") + "/login/"
        with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - https only
            headers = response.headers
            cookies = headers.get_all("Set-Cookie") or []
        problems = header_problems(headers, cookies)
        if problems:
            for line in problems:
                self.stdout.write(self.style.ERROR(line))
            raise CommandError("The header check failed.")
        self.stdout.write(self.style.SUCCESS(f"All security headers are right on {url}"))
