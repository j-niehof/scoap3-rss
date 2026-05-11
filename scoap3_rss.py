"""
scoap3_rss.py

Fetches the 20 most recent SCOAP3 articles affiliated with CERN or the
United States and writes them to an RSS 2.0 file: scoap3_feed.xml

Run:
    python3 scoap3_rss.py

Requires:
    python3 -m pip install requests
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import time
import re
import html

# ── Configuration ────────────────────────────────────────────────────────────
API_BASE = "https://repo.scoap3.org/api/records/"
PAGE_SIZE = 10
FETCH_PAGES = 10      # Scan up to 100 recent articles
FEED_ITEMS = 20
OUTPUT_FILE = "scoap3_feed.xml"

COUNTRY_FILTER = ["cern", "united states", "usa", "u.s.a"]
# ─────────────────────────────────────────────────────────────────────────────


def clean_text(value):
    """
    Remove HTML/XML tags (including MathML) and normalize whitespace.
    """
    if not value:
        return ""

    # Convert HTML entities to normal characters
    value = html.unescape(value)

    # Remove all tags such as <math>, <mi>, <msub>, etc.
    value = re.sub(r"<[^>]+>", "", value)

    # Collapse repeated whitespace
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def matches_filter(metadata):
    """
    Return True if any author affiliation matches our country filter.
    """
    for author in metadata.get("authors", []):
        for affil in author.get("affiliations", []):
            country = affil.get("country", "").lower()
            value = affil.get("value", "").lower()

            for term in COUNTRY_FILTER:
                if term in country or term in value:
                    return True

    return False


def short_title(metadata):
    """
    Shortened title for progress messages.
    """
    titles = metadata.get("titles", [])
    title = titles[0].get("title", "Untitled") if titles else "Untitled"
    title = clean_text(title)

    if len(title) > 60:
        return title[:60] + "..."
    return title


def fetch_articles():
    """
    Fetch recent articles from the SCOAP3 API and keep matching records.
    """
    matched = []

    for page in range(1, FETCH_PAGES + 1):
        print(f"  Fetching page {page} ...")

        params = {
            "format": "json",
            "size": PAGE_SIZE,
            "page": page,
        }

        try:
            response = requests.get(API_BASE, params=params, timeout=15)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"  WARNING: request failed ({e})")
            continue

        data = response.json()
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
    """
    Return a datetime for sorting.
    """
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
            pass

    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def rfc822(dt):
    """
    Format datetime as RSS-compatible date.
    """
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def build_rss(articles):
    """
    Build the RSS XML tree.
    """
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = (
        "SCOAP3 - Recent Articles (CERN / United States)"
    )
    ET.SubElement(channel, "link").text = "https://repo.scoap3.org/"
    ET.SubElement(channel, "description").text = (
        "20 most recent open-access high-energy physics articles from "
        "SCOAP3 with CERN or United States affiliations."
    )
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "lastBuildDate").text = rfc822(
        datetime.now(tz=timezone.utc)
    )

    for metadata in articles:
        item = ET.SubElement(channel, "item")

        # Title
        titles = metadata.get("titles", [])
        title_text = titles[0].get("title", "Untitled") if titles else "Untitled"
        title_text = clean_text(title_text)
        ET.SubElement(item, "title").text = title_text

        # Link (prefer DOI)
        dois = metadata.get("dois", [])
        if dois:
            doi = dois[0].get("value", "")
            link = f"https://doi.org/{doi}" if doi else ""
        else:
            link = ""

        if not link:
            control_number = metadata.get("control_number", "")
            if control_number:
                link = f"https://repo.scoap3.org/records/{control_number}"
            else:
                link = "https://repo.scoap3.org/"

        ET.SubElement(item, "link").text = link

        # Description / abstract
        abstracts = metadata.get("abstracts", [])
        if abstracts:
            abstract_text = abstracts[0].get("value", "")
        else:
            abstract_text = "No abstract available."

        abstract_text = clean_text(abstract_text)
        ET.SubElement(item, "description").text = abstract_text[:1000]

        # Journal title
        publication_info = metadata.get("publication_info", [])
        if publication_info:
            journal = publication_info[0].get("journal_title", "")
            if journal:
                ET.SubElement(item, "source", url=link).text = journal

        # Authors
        authors = metadata.get("authors", [])
        author_names = [
            author.get("full_name", "")
            for author in authors[:5]
            if author.get("full_name")
        ]

        if len(authors) > 5:
            author_names.append("et al.")

        if author_names:
            ET.SubElement(item, "author").text = "; ".join(author_names)

        # Publication date
        ET.SubElement(item, "pubDate").text = rfc822(parse_date(metadata))

        # GUID
        ET.SubElement(item, "guid", isPermaLink="false").text = link

    return ET.ElementTree(rss)


def indent_xml(elem, level=0):
    """
    Pretty-print the XML.
    """
    pad = "\n" + "  " * level

    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "  "

        for child in elem:
            indent_xml(child, level + 1)

        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = pad
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
