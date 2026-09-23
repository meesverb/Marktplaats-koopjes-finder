"""Fetch Trek NL archive pages (/a/<id>/) and extract the spec table."""
import json, re, sys, html
import wb

EXCLUDE_NAME = re.compile(r"(?i)^(zektor|domane\+|ion\b)")


def parse(h):
    specs = []
    for dt, dd in re.findall(r'<dt class="details-list__title[^"]*">\s*(.*?)</dt>\s*<dd class="details-list__definition[^"]*">(.*?)</dd>', h, re.S):
        k = html.unescape(re.sub(r"<[^>]+>", " ", dt)).strip()
        v = html.unescape(re.sub(r"<[^>]+>", " ", dd))
        v = re.sub(r"\s+", " ", v).strip()
        if k and v:
            specs.append([k, v])
    title = re.search(r"<title>(.*?)</title>", h, re.S)
    return specs, (html.unescape(title.group(1)).strip() if title else "")


def main():
    items = json.load(open("trek_archive.json"))
    out = {}
    try:
        out = json.load(open("trek_specs.json"))
    except Exception:
        pass
    for n, r in enumerate(items):
        if EXCLUDE_NAME.match(r["displayName"]):
            continue
        key = f"{r['year']}|{r['id']}"
        if key in out:
            continue
        url = "https://www.trekbikes.com/nl/nl_NL" + r["productUrl"].replace("/p/", "/a/")
        h = wb.get(url, delay=1.0)
        if not h:
            out[key] = {"error": "fetch", "url": url, **r}
            continue
        specs, title = parse(h)
        out[key] = {"url": url, "title": title, "specs": specs, **r}
        if n % 25 == 0:
            json.dump(out, open("trek_specs.json", "w"), ensure_ascii=False)
            print(n, len(out), r["displayName"], len(specs), flush=True)
    json.dump(out, open("trek_specs.json", "w"), ensure_ascii=False)
    print("done", len(out))


if __name__ == "__main__":
    main()
