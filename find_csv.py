import json

import httpx
import urllib3

with open('rn_cookies.json') as f:
    raw = json.load(f)

cookies = {c['name']: c['value'] for c in raw}
base = 'https://ip.ext.net.nokia.com'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
    'Referer': 'https://ip.ext.net.nokia.com/s2/rn/sros',
}

urllib3.disable_warnings()

with httpx.Client(follow_redirects=True, timeout=30, verify=False, cookies=cookies, headers=headers) as client:

    # Fetch the rnQuery JS
    js_files = [
        '/s2/assets/rnQuery-VuvMszzC.js',
        '/s2/assets/rn-3FjnJMkB.js',
        '/s2/assets/ajax-DHKej5tZ.js',
    ]

    for js_path in js_files:
        r = client.get(base + js_path)
        print(f'\n=== {js_path} (status={r.status_code}, size={len(r.text)}) ===')
        print(r.text[:3000])

        # Save to file for inspection
        fname = js_path.split('/')[-1]
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(r.text)
        print(f'Saved to {fname}')
