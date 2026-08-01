"""TEMPORARY PROBE — delete before merge.

Determines, from CI's egress IP, whether psni.police.uk and policeombudsman.org
are actually Cloudflare-blocked or whether the README's five
"Cloudflare-blocked" entries were diagnosed from a datacentre IP.

Prints diagnostics; never fails, so it cannot break the suite.
"""

from bolster.utils.web import session

INDEX = "https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics"

TARGETS = {
    "psni_root": "https://www.psni.police.uk/",
    "psni_official_stats_index": INDEX,
    "psni_recorded_crime": f"{INDEX}/police-recorded-crime-statistics",
    "psni_pace": f"{INDEX}/police-and-criminal-evidence-pace-order",
    "poni_root": "https://www.policeombudsman.org/",
    "poni_annual": "https://www.policeombudsman.org/statistics-and-research/complaint-statistics-in-northern-ireland",
    "poni_quarterly": "https://www.policeombudsman.org/statistics-and-research/quarterly-reports",
}


def _probe(url: str) -> str:
    try:
        r = session.get(url, timeout=30)
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        return f"EXC {type(exc).__name__}: {exc}"
    body = r.text[:400].lower()
    blocked = "you have been blocked" in body or "attention required" in body
    return f"HTTP {r.status_code} server={r.headers.get('server', '?')} len={len(r.content)} cloudflare_block={blocked}"


def test_probe_egress_identity():
    """Report CI's public egress IP so the ASN can be compared against local."""
    for svc in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            print(f"\nEGRESS {svc} -> {session.get(svc, timeout=15).text.strip()}")
        except Exception as exc:  # noqa: BLE001
            print(f"\nEGRESS {svc} -> failed: {exc}")


def test_probe_target_reachability():
    """Report reachability of every PSNI/PONI page the README calls blocked."""
    print("\n--- PSNI / PONI reachability from CI ---")
    for name, url in TARGETS.items():
        print(f"{name:32s} {_probe(url)}")


def test_probe_enumerate_official_statistics_links():
    """List every official-statistics publication link, to map the five unbuilt sources."""
    from bs4 import BeautifulSoup

    try:
        r = session.get(INDEX, timeout=30)
    except Exception as exc:  # noqa: BLE001
        print(f"\nINDEX fetch failed: {exc}")
        return
    print(f"\n--- official-statistics index: HTTP {r.status_code} ---")
    if r.status_code != 200:
        return
    seen = set()
    for a in BeautifulSoup(r.content, "html.parser").find_all("a", href=True):
        href = a["href"]
        if "official-statistics/" in href and href not in seen:
            seen.add(href)
            print(f"  {a.get_text(strip=True)[:60]:60s} {href}")
