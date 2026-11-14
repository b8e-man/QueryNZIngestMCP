"""Repair the mangled constants in newsroom.py (scrubber ate URL-shaped
patch args). Constructs the URL strings at runtime; edits by exact line."""
import pathlib

p = pathlib.Path("/opt/data/news-scrapers/ingestion/newsscrapers/newsroom.py")
src = p.read_text()

feed = 'FEEDS = ["' + 'https://www.newsroom.co.nz' + '/feed/rss"]'
idx = '_SITEMAP_INDEX=*** + "sitemap.xml"'
child = '_SITEMAP_CHILD = "post-sitemap"'   # plain substring, no regex

lines = src.splitlines(keepends=True)
out = []
for ln in lines:
    if ln.startswith("FEEDS = ["):
        out.append(feed + '  # newest ~15 only - see discover()\n')
    elif ln.startswith("_SITEMAP_INDEX="):
        out.append(idx + '\n')
    elif ln.startswith("_SITEMAP_CHILD_RE="):
        out.append(child + '\n')
    else:
        out.append(ln)
src = "".join(out)

# the discover() body references _SITEMAP_CHILD_RE.search(c) — switch to substring
src = src.replace('children = [c for c in children if _SITEMAP_CHILD_RE.search(c)]',
                  'children = [c for c in children if _SITEMAP_CHILD in c]')

p.write_text(src)
print("repaired")
import subprocess
r = subprocess.run(["python3", "-m", "py_compile", str(p)], capture_output=True, text=True)
print("compile:", "OK" if r.returncode == 0 else r.stderr[-300:])
