#!/usr/bin/env python3
"""Deploy tina_recovery_dashboard.html to Static.app via their API."""

import json
import os
import sys
import zipfile
from pathlib import Path

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

ROOT = Path(__file__).resolve().parent
HTML_FILE = ROOT / "tina_recovery_dashboard.html"
API_KEY = os.environ.get("STATIC_APP_API_KEY", "")

if not API_KEY:
    print("ERROR: Set STATIC_APP_API_KEY env var")
    sys.exit(1)

BASE = "https://static.app"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
}


def zip_dashboard():
    """Create a zip containing just the dashboard HTML as index.html."""
    zip_path = ROOT / "deploy.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(HTML_FILE, arcname="index.html")
    return zip_path


def upload_zip(zip_path):
    """Upload zip to Static.app and return the response."""
    url = f"{BASE}/api/files/upload-temporary-zip"
    with open(zip_path, "rb") as f:
        files = {"file": ("deploy.zip", f, "application/zip")}
        resp = requests.post(url, headers=HEADERS, files=files, timeout=60)
    print(f"Upload response: {resp.status_code}")
    print(resp.text[:500])
    return resp.json() if resp.ok else None


def list_sites():
    """List all sites on the account."""
    url = f"{BASE}/api/sites"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    print(f"List sites response: {resp.status_code}")
    print(resp.text[:1000])
    return resp.json() if resp.ok else None


def deploy_site(zip_path, pid=None):
    """Deploy a site. If pid is given, update existing site."""
    if pid:
        url = f"{BASE}/api/sites/{pid}/deploy"
    else:
        url = f"{BASE}/api/sites/deploy"

    with open(zip_path, "rb") as f:
        files = {"file": ("deploy.zip", f, "application/zip")}
        data = {}
        resp = requests.post(url, headers=HEADERS, files=files, data=data, timeout=120)

    print(f"Deploy response: {resp.status_code}")
    print(resp.text[:1000])
    return resp.json() if resp.ok else None


def main():
    print("=== Static.app Deploy ===")
    print(f"Dashboard: {HTML_FILE}")
    print(f"API Key: {API_KEY[:10]}...")

    # Step 1: Create zip
    print("\n--- Step 1: Creating zip ---")
    zip_path = zip_dashboard()
    print(f"Created: {zip_path} ({zip_path.stat().st_size} bytes)")

    # Step 2: Try listing sites first to verify auth
    print("\n--- Step 2: Verifying API key (list sites) ---")
    sites = list_sites()

    # Step 3: Try deploying
    print("\n--- Step 3: Deploying ---")

    # Try the upload-temporary-zip endpoint first
    print("\nTrying /api/files/upload-temporary-zip ...")
    result = upload_zip(zip_path)

    if result and "url" in str(result).lower():
        print(f"\n✅ Upload successful!")
        print(json.dumps(result, indent=2))
    else:
        # Try direct site deploy
        print("\nTrying /api/sites/deploy ...")
        result = deploy_site(zip_path)

        if result:
            print(f"\n✅ Deploy successful!")
            print(json.dumps(result, indent=2))
        else:
            print("\n❌ Deploy failed. Trying alternative endpoints ...")

            # Try with different endpoint patterns
            for endpoint in ["/api/upload", "/api/deploy", "/api/sites/create"]:
                print(f"\nTrying {endpoint} ...")
                with open(zip_path, "rb") as f:
                    files = {"file": ("deploy.zip", f, "application/zip")}
                    resp = requests.post(
                        f"{BASE}{endpoint}",
                        headers=HEADERS,
                        files=files,
                        timeout=60,
                    )
                    print(f"  {resp.status_code}: {resp.text[:300]}")
                    if resp.ok and resp.text.strip() not in ("", '{"message":""}'):
                        print(f"  ✅ {endpoint} worked!")
                        break

    # Cleanup
    zip_path.unlink(missing_ok=True)
    print("\nDone.")


if __name__ == "__main__":
    main()
