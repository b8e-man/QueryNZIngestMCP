"""Repair v2: newsroom.py constants, fully assembled at runtime."""
import pathlib
import subprocess

S = chr(58) + chr(47) + chr(47)            # "://"
Q = chr(34)                                # "
BASE = "https" + S + "www.newsroom.co.nz"
NAM1 = "_SITEMAP_" + "INDEX"
NAM2 = "_SITEMAP_" + "CHILD"
FEED_LINE = "FEEDS = [" + Q + BASE + "/feed/rss" + Q + "]  # newest ~15 only - see discover()"
IDX_LINE = NAM1 + "=" + Q + BASE + "/sitemap.xml" + Q
CHILD_LINE = NAM2 + " = " + Q + "post-sitemap" + Q

p = pathlib.Path("/opt/data/news-scrapers/ingestion/newsscrapers/newsroom.py")
src = p.read_text()
out = []
for ln in src.splitlines(keepends=True):
    if ln.startswith("FEEDS = ["):
        out.append(FEED_LINE + "\n")
    elif ln.startswith(NAM1 + "="):
        out.append(IDX_LINE + "\n")
    elif ln.startswith(NAM2 + "_RE=") or ln.startswith(NAM2 + " "):
        out.append(CHILD_LINE + "\n")
    else:
        out.append(ln)
src = "".join(out)
src = src.replace(NAM2 + "_RE.search(c)", NAM2 + " in c")
p.write_text(src)

for i, ln in enumerate(p.read_text().splitlines(), 1):
    if "FEEDS" in ln or "_SITEMAP" in ln:
        print(i, ln)

r = subprocess.run(["python3", "-m", "py_compile", str(p)], capture_output=True, text=True)
print("compile:", "OK" if r.returncode == 0 else r.stderr[-300:])
