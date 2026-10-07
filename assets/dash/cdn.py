"""Pinned avocloud-CDN URLs for the dashboard templates.

The versions live in config/cdn.json and nowhere else (BRANDING.md §12.2: exact
versions, one place per property). A bump is one edit there. Templates read the
result as ``{{ cdn.<name> }}``.
"""
import json
import os

_MANIFEST = os.path.join(os.path.dirname(__file__), "..", "..", "config", "cdn.json")


def _load() -> dict:
    with open(_MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    base = manifest["base"].rstrip("/")
    for pkg, ver in manifest["versions"].items():
        if not ver or ver == "latest" or not ver[0].isdigit() or ver.count(".") < 2:
            raise ValueError(f"config/cdn.json: {pkg} must be an exact version, got {ver!r}")

    def url(pkg: str, path: str) -> str:
        return f"{base}/{pkg}@{manifest['versions'][pkg]}/{path}"

    return {
        "origin": base,
        "fonts_css": url("avocloud-ui-fonts", "fonts.css"),
        # The kit: tokens + components, themed onto Basecoat. Imports avocloud.css,
        # which imports the tokens and the fonts. Load it AFTER basecoat (§12.1).
        "ui_base_css": url("avocloud-ui", "avocloud.base.css"),
        "favicon": url("avocloud-logo", "favicon.ico"),
        "basecoat_css": url("basecoat", "basecoat.cdn.min.css"),
        "basecoat_js": url("basecoat", "js/all.min.js"),
        "tailwind_js": url("tailwindcss-browser", "tailwind-browser.js"),
        "gsap_js": url("gsap", "gsap.min.js"),
        "chartjs_js": url("chartjs", "chart.umd.min.js"),
    }


_CDN = _load()


def cdn_context() -> dict:
    return {"cdn": _CDN}
