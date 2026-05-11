"""
scoap3_rss.py
-------------
Fetches the 20 most recent SCOAP3 articles affiliated with CERN or the
United States and writes them to an RSS 2.0 file: scoap3_feed.xml

Run it:  python3 scoap3_rss.py
Output:  scoap3_feed.xml  (in the same folder as this script)

Requires Python 3.7+ and the 'requests' library.
Install requests if needed:  pip3 install requests
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import time

# ── Configuration ────────────────────────────────────────────────────────────
API_BASE    = "https://repo.scoap3.org/api/records/"
PAGE_SIZE   = 10
FETCH_PAGES = 10   # scan up to 100 articles to find 20 matches
FEED_ITEMS  = 20
OUTPUT_FILE = "scoap3_feed.xml"

COUNTRY_FILTER = ["cern", "united states", "usa", "u.s.a"]
# ─────────────────────────────────────────────────────────────────────────────


def matches_filter(metadata):
    """Return True if any author affiliation matches our country filter."""
    for author in metadata.get("authors", []):
        for affil in author.get("affiliations", []):
            country = affil.get("country", "").lower()
            value   = affil.get("value", "").lower()
            for term in COUNTRY_FILTER:
                if term in country or term in value:
                    return True
    return False


def short_title(metadata):
    titles = metadata.get("titles", [])
    t = titles[0].get("title", "Untitled") if titles else "Untitled"
    return t[:60] + ("..." if len(t) > 60 else "")


def fetch_articles():
    matched = []

    for page in range(1, FETCH_PAGES + 1):
        params = {
            "format": "json",
            "size": PAGE_SIZE,
            "page": page,
        }
        print(f"  Fetching page {page} ...")
        try:
            resp = requests.get(API_BASE, params=params, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  WARNING: request failed ({e})")
            continue

        data = resp.json()

        # Response structure: data -> hits -> hits -> [list of records]
        # Each record has a "metadata" key with the actual article data
        records = data.get("hits", {}).get("hits", [])

        if not records:
            print("  No more results.")
            break

        for record in records:
            metadata = record.get("metadata", {})
            if matches_filter(metadata):
                matched.append(metadata)
                print(f"    matched: {short_title(metadata)}")

        print(f"  Running total: {len(matched)} matching articles after page {page}")

        if len(matched) >= FEED_ITEMS:
            break

        time.sleep(0.4)

    return matched


def parse_date(metadata):
    """Return a datetime for sorting; fall back to epoch if unparseable."""
    raw = ""
    imprints = metadata.get("imprints", [])
    if imprints:
        raw = imprints[0].get("date", "")
    if not raw:
        raw = metadata.get("record_creation_date", "") or metadata.get("created", "")
    raw = raw[:10]
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def rfc822(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def build_rss(articles):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text       = "SCOAP3 - Recent Articles (CERN / United States)"
    ET.SubElement(channel, "link").text        = "https://repo.scoap3.org/"
    ET.SubElement(channel, "description").text = (
        "20 most recent open-access high-energy physics articles from "
        "SCOAP3 with CERN or United States affiliations."
    )
    ET.SubElement(channel, "language").text      = "en"
    ET.SubElement(channel, "lastBuildDate").text = rfc822(datetime.now(tz=timezone.utc))

    for metadata in articles:
        item = ET.SubElement(channel, "item")

        # Title
        titles = metadata.get("titles", [])
        title_text = titles[0].get("title", "Untitled") if titles else "Untitled"
        ET.SubElement(item, "title").text = title_text

        # Link (DOI preferred, fallback to SCOAP3 record page)
        dois = metadata.get("dois", [])
        if dois:
            doi_val = dois[0].get("value", "")
            link = f"https://doi.org/{doi_val}" if doi_val else ""
        else:
            link = ""
        if not link:
            cnum = metadata.get("control_number", "")
            link = f"https://repo.scoap3.org/records/{cnum}" if cnum else "https://repo.scoap3.org/"
        ET.SubElement(item, "link").text = link

        # Abstract (field is "abstracts" not "abstract" per the raw preview)
        abstracts = metadata.get("abstracts", metadata.get("abstract", []))
        abstract_text = abstracts[0].get("value", "") if abstracts else ""
        if not abstract_text:
            abstract_text = "No abstract available."
        ET.SubElement(item, "description").text = abstract_text[:1000]

        # Journal
        pub_info = metadata.get("publication_info", [])
        if pub_info:
            journal = pub_info[0].get("journal_title", "")
            if journal:
                ET.SubElement(item, "source", url=link).text = journal

        # Authors (first 5 + et al.)
        authors = metadata.get("authors", [])
        author_names = [a.get("full_name", "") for a in authors[:5] if a.get("full_name")]
        if len(authors) > 5:
            author_names.append("et al.")
        if author_names:
            ET.SubElement(item, "author").text = "; ".join(author_names)

        # Publication date
        dt = parse_date(metadata)
        ET.SubElement(item, "pubDate").text = rfc822(dt)

        # Unique ID
        ET.SubElement(item, "guid", isPermaLink="false").text = link

    return ET.ElementTree(rss)


def indent_xml(elem, level=0):
    pad = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = pad
        for child in elem:
            indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = pad


def main():
    print("Fetching articles from SCOAP3 API ...")
    articles = fetch_articles()
    print(f"  Retrieved {len(articles)} matching articles total.")

    if not articles:
        print("No articles found.")
        return

    articles.sort(key=parse_date, reverse=True)
    articles = articles[:FEED_ITEMS]
    print(f"  Keeping {len(articles)} most recent for the feed.")

    print("Building RSS feed ...")
    tree = build_rss(articles)
    indent_xml(tree.getroot())
    tree.write(OUTPUT_FILE, encoding="utf-8", xml_declaration=True)
    print(f"Done! Feed saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
