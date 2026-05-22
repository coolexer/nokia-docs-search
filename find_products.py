"""Find all product slugs from the Nokia RN portal navigation."""
import json
import re

import httpx
import urllib3
from selectolax.lexbor import LexborHTMLParser

with open('rn_cookies.json') as f:
    raw = json.load(f)
cookies = {c['name']: c['value'] for c in raw}

BASE = 'https://ip.ext.net.nokia.com'
CB = '?cb=1778665087235'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
    'Referer': 'https://ip.ext.net.nokia.com/s2/rn',
}

urllib3.disable_warnings()

with httpx.Client(follow_redirects=True, timeout=30, verify=False, cookies=cookies, headers=HEADERS) as client:

    # Fetch main RN page to find all product links
    r = client.get(BASE + '/s2/rn')
    tree = LexborHTMLParser(r.text)

    print("=== Links on /s2/rn ===")
    for a in tree.css('a[href]'):
        href = a.attributes.get('href', '')
        text = a.text(strip=True)[:60]
        if '/rn/' in href or '/s2/rn' in href:
            print(f"  {text!r:40s} -> {href}")

    # Extract product slugs from hrefs
    slugs = re.findall(r'/s2/rn/([a-z0-9_-]+)', r.text)
    slugs = sorted(set(slugs))
    print(f"\nFound slugs: {slugs}")

    # Also look in any JS for all products
    # Try common slug patterns
    print("\n=== Testing more product slugs ===")
    candidates = slugs + [
        'srl', 'sr-linux', 'srlinux-26-3',
        '7250ixr', '7250-ixr', 'ixr-e',
        '7705sar', '7705-sar', 'sar-gen2',
        '7705sargen2', 'sargen2',
        'nsp-n', 'nsp-s',
    ]
    for slug in candidates:
        url = f'{BASE}/s2/rn-ipex1-{slug}.csv{CB}'
        r2 = client.get(url)
        ct = r2.headers.get('content-type', '')
        if r2.status_code == 200 and 'html' not in ct and len(r2.text) > 500:
            print(f"  [OK] {slug}: {r2.status_code} {len(r2.text):,} chars  ct={ct}")
            with open(f'rn_{slug}.csv', 'w', encoding='utf-8') as f:
                f.write(r2.text)
        else:
            print(f"  [NO] {slug}: {r2.status_code} {len(r2.text)} chars")

    # Also look at the JS bundle for product list
    r3 = client.get(BASE + '/s2/assets/App-CHQRQ44q.js')
    if r3.status_code == 200:
        # Look for product slugs in the JS
        products = re.findall(r'(?:slug|product|name)["\s]*:\s*["\']([a-z0-9-]+)["\']', r3.text)
        print(f"\nProducts found in App.js: {set(products)}")
        # Also look for rn-ipex1 pattern
        ipex = re.findall(r'rn-ipex1-([a-z0-9-]+)', r3.text)
        print(f"ipex1 slugs in App.js: {set(ipex)}")
        with open('App-CHQRQ44q.js', 'w', encoding='utf-8') as f:
            f.write(r3.text)
