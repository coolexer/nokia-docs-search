r"""
Probe Nokia RN portal via CDP -- connects to already-running Chrome.

Steps:
  1. Close all Chrome windows.
  2. Launch Chrome with remote debugging:
       "C:\Program Files\Google\Chrome\Application\chrome.exe"
           --remote-debugging-port=9222
           --user-data-dir="C:\Users\vikharev\AppData\Local\Google\Chrome\User Data\Default"
  3. In that Chrome, navigate to https://ip.ext.net.nokia.com/s2/rn
     (SSO should log you in automatically).
  4. Run this script:
       python probe_rn.py

The script will connect to the running Chrome and scrape the page.
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "https://ip.ext.net.nokia.com/s2/rn"
HOST = "ip.ext.net.nokia.com"
CDP_URL = "http://localhost:9222"


def analyze_and_save(html: str, name: str) -> None:
    from selectolax.lexbor import LexborHTMLParser

    out = Path(f"probe_{name}.html")
    out.write_text(html, encoding="utf-8")
    print(f"  [saved] {out.resolve()}")

    tree = LexborHTMLParser(html)
    title = tree.css_first("title")
    print(f"  Title : {title.text(strip=True) if title else '?'}")
    print(f"  Size  : {len(html)} chars")

    if "login.microsoftonline" in html[:6000]:
        print("  [!] Still on login page.")
        return

    print("  -- Structural elements --")
    for sel in ["body", "main", "article", "#core", "#content",
                "h1", "h2", "h3", "h4", "table", "ul", "nav",
                "[class*='rn']", "[class*='release']", "[class*='product']",
                "[id*='rn']", "[id*='content']"]:
        nodes = tree.css(sel)
        if nodes:
            cls = nodes[0].attributes.get("class", "")[:55]
            eid = nodes[0].attributes.get("id", "")
            print(f"    {sel:38s}  n={len(nodes):4d}  id='{eid}' cls='{cls}'")

    print("  -- All IDs --")
    for el in tree.css("[id]")[:30]:
        print(f"    <{el.tag} id='{el.attributes.get('id')}' "
              f"cls='{el.attributes.get('class','')[:50]}'>")

    print("  -- Links (first 80) --")
    for a in tree.css("a[href]")[:80]:
        href = a.attributes.get("href", "")
        text = a.text(strip=True)[:70]
        print(f"    {text!r:60s}  {href}")

    print("  -- Tables --")
    for i, tbl in enumerate(tree.css("table")[:5]):
        rows = tbl.css("tr")
        print(f"    Table {i}: {len(rows)} rows")
        for r in rows[:3]:
            cells = [c.text(strip=True)[:25] for c in r.css("td,th")]
            print(f"      {cells}")


def main():
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    print(f"Connecting to Chrome at {CDP_URL} ...")
    print(f"Target: {BASE_URL}")
    print()

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"ERROR: Cannot connect to Chrome CDP: {e}")
            print()
            print("Make sure Chrome is running with:")
            print('  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"')
            print('      --remote-debugging-port=9222')
            print('      --user-data-dir="C:\\Users\\vikharev\\AppData\\Local\\Google\\Chrome\\User Data\\Default"')
            return

        print(f"Connected! Contexts: {len(browser.contexts)}")

        # Use existing context (has all cookies/session)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        pages = ctx.pages
        print(f"Open pages: {[p.url for p in pages]}")

        # Find or create the RN page
        rn_page = None
        for pg in pages:
            if HOST in pg.url:
                rn_page = pg
                print(f"Found existing RN tab: {pg.url}")
                break

        if rn_page is None:
            print("No RN tab found — navigating to it...")
            rn_page = ctx.new_page()
            rn_page.goto(BASE_URL, timeout=60_000, wait_until="domcontentloaded")

        # Wait for load
        try:
            rn_page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout:
            pass

        print(f"Current URL: {rn_page.url}")

        if "login.microsoft" in rn_page.url:
            print("[!] Not logged in. Navigate to the Nokia RN page in Chrome first.")
            browser.close()
            return

        # Capture main page
        html = rn_page.content()
        print("\n=== MAIN PAGE ===")
        analyze_and_save(html, "rn_main")

        # Save session cookies for future httpx use
        cookies = ctx.cookies()
        nokia_cookies = [c for c in cookies if HOST in c.get("domain", "")]
        print(f"\nNokia cookies: {len(nokia_cookies)}")
        for c in nokia_cookies:
            print(f"  {c['name']} = {c['value'][:40]}...")

        import json
        Path("rn_cookies.json").write_text(json.dumps(nokia_cookies, indent=2))
        print("Cookies saved to rn_cookies.json")

        # Probe first few internal links
        from selectolax.lexbor import LexborHTMLParser
        tree = LexborHTMLParser(html)
        probed = 0
        for a in tree.css("a[href]"):
            href = a.attributes.get("href", "")
            if not href or href.startswith("#") or href.startswith("mailto"):
                continue
            full = href if href.startswith("http") else f"https://{HOST}{href}"
            if HOST not in full:
                continue
            if full.rstrip("/") == BASE_URL.rstrip("/"):
                continue
            print(f"\n=== SUB PAGE {probed}: {full} ===")
            try:
                rn_page.goto(full, timeout=20_000, wait_until="domcontentloaded")
                rn_page.wait_for_load_state("networkidle", timeout=10_000)
                sub = rn_page.content()
                analyze_and_save(sub, f"sub_{probed}")
                probed += 1
                if probed >= 3:
                    break
            except Exception as e:
                print(f"  Error: {e}")

        browser.disconnect()
        print("\nDone! Check probe_*.html files.")


if __name__ == "__main__":
    main()
