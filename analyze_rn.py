"""Analyze saved Nokia RN HTML file. Usage: python analyze_rn.py rn_page.html"""
import sys
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser

f = Path(sys.argv[1] if len(sys.argv) > 1 else "rn_page.html")
html = f.read_text(encoding="utf-8", errors="replace")
tree = LexborHTMLParser(html)

title = tree.css_first("title")
print(f"Title : {title.text(strip=True) if title else '?'}")
print(f"Size  : {len(html):,} chars\n")

print("=== Structural elements ===")
for sel in ["body","main","article","#core","#content",".content",
            "h1","h2","h3","h4","table","ul","nav","iframe",
            "[class*='rn']","[class*='release']","[class*='product']"]:
    nodes = tree.css(sel)
    if nodes:
        cls = nodes[0].attributes.get("class","")[:55]
        eid = nodes[0].attributes.get("id","")
        print(f"  {sel:38s}  n={len(nodes):4d}  id='{eid}' cls='{cls}'")

print("\n=== All IDs ===")
for el in tree.css("[id]")[:40]:
    print(f"  <{el.tag} id='{el.attributes.get('id')}' cls='{el.attributes.get('class','')[:50]}'>")

print("\n=== Links (first 100) ===")
for a in tree.css("a[href]")[:100]:
    href = a.attributes.get("href","")
    text = a.text(strip=True)[:70]
    print(f"  {text!r:60s}  {href}")

print("\n=== Tables ===")
for i, tbl in enumerate(tree.css("table")[:5]):
    rows = tbl.css("tr")
    print(f"  Table {i}: {len(rows)} rows")
    for r in rows[:4]:
        cells = [c.text(strip=True)[:30] for c in r.css("td,th")]
        print(f"    {cells}")
