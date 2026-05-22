"""Download all Nokia RN CSV files and show structure."""
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
    'Referer': 'https://ip.ext.net.nokia.com/s2/rn',
}

# All products found in App.js
PRODUCTS = ['sros', 'srl', 'sas', 'mag-c', 'eda']

urllib3.disable_warnings()

with httpx.Client(follow_redirects=True, timeout=60, verify=False, cookies=cookies, headers=HEADERS) as client:
    for prod in PRODUCTS:
        url = f'{BASE}/s2/rn-ipex1-{prod}.csv{CB}'
        print(f'Fetching {prod}...', end=' ', flush=True)
        r = client.get(url)
        ct = r.headers.get('content-type', '')

        if r.status_code == 200 and 'html' not in ct and len(r.text) > 500:
            fname = f'rn_{prod}.csv'
            with open(fname, 'w', encoding='utf-8') as f:
                f.write(r.text)

            reader = csv.DictReader(io.StringIO(r.text))
            rows = list(reader)
            # First row is context row
            ctx = rows[0] if rows else {}
            data_rows = rows[1:] if rows else []

            print(f'OK  {len(r.text):>10,} chars  {len(data_rows):>6,} entries')
            print(f'    Fields : {list(ctx.keys())}')

            # Show sections
            sections = {}
            for row in data_rows:
                s = row.get('section', '') or 'unknown'
                sections[s] = sections.get(s, 0) + 1
            print(f'    Sections: {dict(sorted(sections.items(), key=lambda x: -x[1]))}')

            # Show sample
            for row in data_rows[:2]:
                title = row.get('title','')[:70]
                section = row.get('section','')
                platforms = row.get('platforms','')[:50]
                releases = row.get('releaseList','')[:40]
                text_len = len(row.get('text',''))
                print(f'    Sample: {title!r}')
                print(f'            section={section!r}  platforms={platforms!r}')
                print(f'            releases={releases!r}  text_len={text_len}')
            print()
        else:
            print(f'FAIL  status={r.status_code}  ct={ct}  size={len(r.text)}')

    # Also fetch EOL JSON (SROS only)
    print('Fetching rn-eol.json...', end=' ', flush=True)
    r = client.get(BASE + '/s2/rn-eol.json' + CB)
    if r.status_code == 200:
        with open('rn_eol.json', 'w', encoding='utf-8') as f:
            f.write(r.text)
        data = json.loads(r.text)
        print(f'OK  {len(r.text):>10,} chars  {len(data):>6,} entries')
        # Show types
        types = {}
        for e in data:
            t = e.get('type','?')
            types[t] = types.get(t, 0) + 1
        print(f'    Types: {types}')
    else:
        print(f'FAIL {r.status_code}')
