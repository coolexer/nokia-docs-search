"""Fetch Nokia RN CSV files and show structure."""
import csv
import io
import json

import httpx
import urllib3

with open('rn_cookies.json') as f:
    raw = json.load(f)
cookies = {c['name']: c['value'] for c in raw}

BASE = 'https://ip.ext.net.nokia.com'
CB = '?cb=1778665087235'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
    'Referer': 'https://ip.ext.net.nokia.com/s2/rn/sros',
}

urllib3.disable_warnings()

PRODUCTS = ['sros', 'srlinux', 'ixr', 'sar', 'sas', 'nsp', '7705sar', '7250ixr', '7210sas']

with httpx.Client(follow_redirects=True, timeout=30, verify=False, cookies=cookies, headers=HEADERS) as client:

    # First, try to get the manifest to see all products
    r = client.get(BASE + '/s2/manifest.webmanifest' + CB)
    print(f'Manifest: {r.status_code} {len(r.text)} chars')
    if r.status_code == 200:
        print(r.text[:500])
        with open('rn_manifest.json', 'w') as f:
            f.write(r.text)

    print()

    # Try fetching CSV for each product slug
    for prod in PRODUCTS:
        url = f'{BASE}/s2/rn-ipex1-{prod}.csv{CB}'
        r = client.get(url)
        if r.status_code == 200 and 'text/csv' in r.headers.get('content-type','') or (r.status_code == 200 and len(r.text) > 1000 and ',' in r.text[:200]):
            print(f'[OK] {prod}: {r.status_code} {len(r.text):,} chars')
            # Save CSV
            with open(f'rn_{prod}.csv', 'w', encoding='utf-8') as f:
                f.write(r.text)
            # Show first few rows
            reader = csv.DictReader(io.StringIO(r.text))
            rows = list(reader)
            print(f'  Rows: {len(rows)}')
            if rows:
                print(f'  Fields: {list(rows[0].keys())}')
                # Show first 3 data rows
                for row in rows[:3]:
                    print(f'  Row: title={row.get("title","")[:60]!r}')
                    print(f'       section={row.get("section","")!r}')
                    print(f'       platforms={row.get("platforms","")[:60]!r}')
                    print(f'       releases={row.get("releaseList","")[:60]!r}')
                    print()
        elif r.status_code == 200:
            print(f'[?] {prod}: {r.status_code} {len(r.text)} chars (not CSV?)')
            print(f'  Content-Type: {r.headers.get("content-type","")}')
            print(f'  First 100: {r.text[:100]!r}')
        else:
            print(f'[NO] {prod}: {r.status_code}')

    # Also fetch sros EOL
    r = client.get(BASE + '/s2/rn-eol.json' + CB)
    print(f'\nEOL JSON: {r.status_code} {len(r.text)} chars')
    if r.status_code == 200:
        with open('rn_eol.json', 'w') as f:
            f.write(r.text)
        data = json.loads(r.text)
        print(f'  Entries: {len(data)}')
        if data:
            print(f'  First: {json.dumps(data[0])[:200]}')
