#!/usr/bin/env python3
"""Export tina_recovery_dashboard.html to a dark-theme PDF (screen colors + backgrounds)."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_HTML = ROOT / "tina_recovery_dashboard.html"
DEFAULT_PDF = ROOT / "tina_recovery_dashboard_dark.pdf"


def export_pdf(html_path: Path, pdf_path: Path, width_px: int = 1100) -> None:
    from playwright.sync_api import sync_playwright

    html_uri = html_path.resolve().as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width_px, "height": 900})
        page.goto(html_uri, wait_until="networkidle")
        page.wait_for_timeout(800)
        page.emulate_media(media="screen")
        height_px = page.evaluate(
            "() => Math.ceil(document.documentElement.scrollHeight)"
        )
        height_px = max(height_px, 900)
        page.pdf(
            path=str(pdf_path),
            print_background=True,
            width=f"{width_px}px",
            height=f"{height_px}px",
            margin={"top": "0.35in", "bottom": "0.35in", "left": "0.35in", "right": "0.35in"},
            scale=1,
        )
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export recovery dashboard as dark PDF")
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--out", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--width", type=int, default=1100)
    args = parser.parse_args()
    if not args.html.is_file():
        raise SystemExit(f"HTML not found: {args.html}")
    export_pdf(args.html, args.out, width_px=args.width)
    print(f"Wrote {args.out.name}")


if __name__ == "__main__":
    main()
