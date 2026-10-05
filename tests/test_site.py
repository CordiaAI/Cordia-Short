"""Contract for the cordiaai.io landing page served by Vercel from site/."""

import json
import unittest
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"


class MarketingSiteTests(unittest.TestCase):
    def setUp(self):
        self.html = (SITE / "index.html").read_text(encoding="utf-8")

    def test_landing_assets_live_under_site_so_they_never_shadow_app_files(self):
        for asset in ("cordia-favicon.ico", "cordia-favicon.png", "cordia-apple-touch-icon.png",
                      "cordia-logo-header.webp", "styles.css"):
            self.assertIn(f"/site/{asset}", self.html)
            self.assertTrue((SITE / "site" / asset).is_file(), asset)
        self.assertNotIn("/static/", self.html)

    def test_account_links_open_the_app_and_classroom_uses_its_live_domain(self):
        self.assertIn('href="https://dashboard.cordiaai.io/?auth=signin"', self.html)
        self.assertIn('href="https://dashboard.cordiaai.io/?auth=register"', self.html)
        self.assertIn('href="https://classroom.cordiaai.io"', self.html)
        self.assertNotIn("cordiacode.com", self.html)
        self.assertNotIn("/dashboard/", self.html)  # Alidora lived on Hostinger; it returns when rebuilt

    def test_nothing_is_sent_to_hostinger_and_old_links_reach_the_app(self):
        config = (SITE / "vercel.json").read_text(encoding="utf-8")
        self.assertNotIn("cordiacode.com", config)
        redirects = {item["source"]: item for item in json.loads(config)["redirects"]}
        self.assertEqual("https://dashboard.cordiaai.io/:path*", redirects["/app/:path*"]["destination"])
        self.assertEqual("auth", redirects["/"]["has"][0]["key"])  # old /?auth= links still open sign-in


if __name__ == "__main__":
    unittest.main()
