"""Cached, polite fetcher for the Wayback Machine and brand sites."""
import hashlib, json, os, re, sys, time, html
import requests

# The cache lives in the working directory, not next to this file: run the
# tools from a scratch directory so nothing lands in the repository.
CACHE = os.path.join(os.getcwd(), "cache")
os.makedirs(CACHE, exist_ok=True)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
S = requests.Session()
S.headers["User-Agent"] = UA
_last = [0.0]


def _key(url):
    return os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest())


def get(url, delay=1.0, tries=6, timeout=60, cache=True):
    p = _key(url)
    if cache and os.path.exists(p):
        with open(p, encoding="utf-8", errors="ignore") as f:
            return f.read()
    err = None
    for i in range(tries):
        wait = delay - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            r = S.get(url, timeout=timeout)
            _last[0] = time.time()
            if r.status_code == 200 and "Temporarily Offline" not in r.text[:3000]:
                r.encoding = r.encoding or "utf-8"
                t = r.text
                if cache:
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(t)
                return t
            if r.status_code in (404, 410):
                return None
            err = f"HTTP {r.status_code}"
        except Exception as e:  # noqa
            _last[0] = time.time()
            err = repr(e)[:200]
        time.sleep(min(60, 3 * 2 ** i))
    print(f"FAIL {url}: {err}", file=sys.stderr)
    return None


def cdx(url, **params):
    q = {"url": url, "output": "json", "filter": "statuscode:200"}
    q.update(params)
    qs = "&".join(f"{k}={requests.utils.quote(str(v), safe=':/*')}" for k, v in q.items())
    t = get("https://web.archive.org/cdx/search/cdx?" + qs, delay=1.5)
    if not t:
        return []
    try:
        rows = json.loads(t)
    except ValueError:
        return []
    if not rows:
        return []
    head = rows[0]
    return [dict(zip(head, r)) for r in rows[1:]]


def wb(ts, url):
    """Raw archived page (id_ = without the Wayback toolbar)."""
    return get(f"https://web.archive.org/web/{ts}id_/{url}", delay=1.5)


def text(h):
    h = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d|dt|dd|td|th)>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h)
    h = re.sub(r"[ \t\r\f\v]+", " ", h)
    h = re.sub(r"\n\s*\n+", "\n", h)
    return h.strip()


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "cdx":
        extra = dict(a.split("=", 1) for a in sys.argv[3:])
        for r in cdx(sys.argv[2], **extra):
            print(r.get("timestamp"), r.get("original"))
    elif cmd == "text":
        print(text(get(sys.argv[2])))
    elif cmd == "wbtext":
        print(text(wb(sys.argv[2], sys.argv[3])))
