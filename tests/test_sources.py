from ingest.sources import normalize_url, original_url, parse_readme, wayback_raw_url

README = """\
# A List of Post-mortems!

## Table of Contents

 - **[Config Errors](#config-errors)**

## Config Errors

[Allegro](https://allegro.tech/2018/08/postmortem.html). E-commerce site went down.
The [Allegro](https://allegro.pl/) platform failed.

[Cloudflare](https://web.archive.org/web/20211006135542/https://blog.cloudflare.com/outage/). A bad config.

## Uncategorized

*Please add more links if you know of any.*

[BrowserStack](https://www.browserstack.com/attack#top). A machine with the [Shellshock](https://en.wikipedia.org/wiki/Shellshock_(software_bug)) bug.

[Allegro](https://allegro.pl/). Duplicate URL, but here as the primary link.

## Other lists of postmortems

[NASA lessons learned database](https://llis.nasa.gov/).

## Contributors

[someone](https://github.com/someone)
"""


def test_parse_primary_entries_and_categories():
    entries = {e.url: e for e in parse_readme(README)}
    primary = [e for e in entries.values() if not e.is_secondary]
    assert sorted(e.company for e in primary) == ["Allegro", "Allegro", "BrowserStack", "Cloudflare"]

    first = entries["https://allegro.tech/2018/08/postmortem.html"]
    assert first.category == "Config Errors"
    # 설명의 마크다운 링크는 텍스트만 남기고, 줄바꿈은 공백으로
    assert first.description == "E-commerce site went down. The Allegro platform failed."


def test_excluded_sections_are_skipped():
    urls = {e.url for e in parse_readme(README)}
    assert "https://llis.nasa.gov/" not in urls
    assert "https://github.com/someone" not in urls


def test_secondary_links_and_parentheses_in_url():
    entries = {e.url: e for e in parse_readme(README)}
    wiki = entries["https://en.wikipedia.org/wiki/Shellshock_(software_bug)"]
    assert wiki.is_secondary
    assert wiki.company == "BrowserStack"


def test_duplicate_url_keeps_primary():
    entries = [e for e in parse_readme(README) if e.url == "https://allegro.pl/"]
    assert len(entries) == 1
    assert not entries[0].is_secondary


def test_fragment_removed():
    assert "https://www.browserstack.com/attack" in {e.url for e in parse_readme(README)}


def test_normalize_url():
    assert normalize_url("HTTPS://Example.COM/A/b?x=1#frag") == "https://example.com/A/b?x=1"
    assert normalize_url("https://example.com") == "https://example.com/"


def test_wayback_urls():
    snap = "https://web.archive.org/web/20211006135542/https://blog.cloudflare.com/outage/"
    assert wayback_raw_url(snap) == "https://web.archive.org/web/20211006135542id_/https://blog.cloudflare.com/outage/"
    assert wayback_raw_url(wayback_raw_url(snap)) == wayback_raw_url(snap)
    assert original_url(snap) == "https://blog.cloudflare.com/outage/"
    assert wayback_raw_url("https://example.com/a") == "https://example.com/a"
