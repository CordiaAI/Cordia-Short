"""Contract for the cordiaai.io landing page served by Vercel from site/."""

import json
import unittest
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"


class MarketingSiteTests(unittest.TestCase):
    def setUp(self):
        self.html = (SITE / "index.html").read_text(encoding="utf-8")
        self.routes = json.loads((SITE / "vercel.json").read_text(encoding="utf-8"))["routes"]

    def test_landing_assets_live_under_site_so_they_never_shadow_app_files(self):
        for asset in ("cordia-favicon.ico", "cordia-favicon.png", "cordia-apple-touch-icon.png",
                      "cordia-logo-header.webp", "styles.css"):
            self.assertIn(f"/site/{asset}", self.html)
            self.assertTrue((SITE / "site" / asset).is_file(), asset)
        self.assertNotIn("/static/", self.html)

    def test_account_links_open_the_app_and_classroom_uses_its_live_domain(self):
        self.assertIn('href="/app?auth=signin"', self.html)
        self.assertIn('href="/app?auth=register"', self.html)
        self.assertIn('href="https://classroom.cordiaai.io"', self.html)
        self.assertNotIn("cordiacode.com", self.html)

    def test_app_routes_reach_the_app_and_everything_else_is_served_here_first(self):
        handled = [route.get("handle") for route in self.routes]
        filesystem = handled.index("filesystem")
        before = self.routes[:filesystem]
        self.assertIn({"src": "/app/?", "dest": "https://cordiacode.com/"}, before)
        self.assertEqual("auth", before[0]["has"][0]["key"])  # old /?auth= links still open sign-in
        self.assertEqual({"src": "/(.*)", "dest": "https://cordiacode.com/$1"}, self.routes[-1])


if __name__ == "__main__":
    unittest.main()
