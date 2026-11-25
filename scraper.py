import re
from bs4 import BeautifulSoup
import requests

try:
    from curl_cffi import requests as curl_requests
    USE_CURL_CFFI = True
except ImportError:
    curl_requests = requests
    USE_CURL_CFFI = False

PRIORITY_KEYWORDS = (
    "use-case", "usecase", "case-stud", "solution", "service",
    "product", "feature", "platform", "what-we-do", "automation",
    "industr", "offering",
)

IGNORE_KEYWORDS = (
    "privacy", "terms", "cookie", "policy", "login", "signup", "register",
    "cart", "checkout", "wp-content", "feed", ".xml", ".png", ".jpg", ".svg",
    "author", "tag", "page/", "tel:", "mailto:", "#",
)

NOISE_TAGS = (
    "script", "style", "nav", "footer", "header", "noscript",
    "svg", "iframe", "canvas", "form", "aside", "dialog", "select", "option",
)

NOISE_ROLES = {"navigation", "banner", "contentinfo", "dialog", "alertdialog"}

NOISE_PATTERNS = (
    "cookie", "consent", "gdpr", "banner-nav", "navbar",
    "nav-menu", "site-footer", "footer-menu", "modal-backdrop",
)


def extract_clean_page_text(html):
    """Extracts clean, readable text from raw HTML after stripping navigation and boilerplate."""
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()

    for elem in soup.find_all(attrs={"role": lambda r: r and r.lower() in NOISE_ROLES}):
        elem.decompose()

    for elem in soup.find_all(True):
        raw_class = elem.get("class", [])
        classes = " ".join(raw_class).lower() if isinstance(raw_class, list) else str(raw_class).lower()
        elem_id = str(elem.get("id", "")).lower()
        if any(pat in classes or pat in elem_id for pat in NOISE_PATTERNS):
            elem.decompose()

    main_area = soup.find("main") or soup.find("article") or soup.body or soup
    lines = [s.strip() for s in main_area.stripped_strings if len(s.strip()) > 1]
    full_text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", full_text).strip()


def map_and_scrape_website_firecrawl(domain, api_key, max_pages=4):
    """
    Uses Firecrawl to map a company website and scrape the highest-signal pages
    (homepage, use cases, solutions, services, products, case studies, etc.).
    """
    if not domain or not api_key:
        return ""

    url = f"https://{domain}" if not domain.startswith(("http://", "https://")) else domain
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print(f"Mapping entire website {url} via Firecrawl...")
    mapped_links = []
    try:
        res = requests.post(
            "https://api.firecrawl.dev/v1/map",
            json={"url": url},
            headers=headers,
            timeout=25,
        )
        if res.status_code == 200:
            mapped_links = res.json().get("links", [])
            print(f"Firecrawl discovered {len(mapped_links)} pages.")
        else:
            print(f"Firecrawl map status: {res.status_code}")
    except Exception as e:
        print(f"Firecrawl map request failed: {e}")

    scored_urls = []
    clean_base = url.rstrip("/")
    for link in mapped_links:
        link_lower = link.lower()
        if any(ign in link_lower for ign in IGNORE_KEYWORDS):
            continue
        score = sum(15 for kw in PRIORITY_KEYWORDS if kw in link_lower)
        depth = link.replace(clean_base, "").count("/")
        score -= depth * 2
        scored_urls.append((score, link))

    scored_urls.sort(key=lambda x: x[0], reverse=True)

    target_urls = [url]
    for _, link in scored_urls:
        if link != url and link.rstrip("/") != clean_base and link not in target_urls:
            target_urls.append(link)
        if len(target_urls) >= max_pages:
            break

    print(f"Scraping {len(target_urls)} key page(s): {target_urls}")

    combined_content = []
    for target in target_urls:
        try:
            res = requests.post(
                "https://api.firecrawl.dev/v1/scrape",
                json={"url": target, "formats": ["markdown"]},
                headers=headers,
                timeout=30,
            )
            if res.status_code == 200:
                page_data = res.json().get("data", {})
                markdown = page_data.get("markdown", "").strip()
                title = page_data.get("metadata", {}).get("title", target)
                if markdown and len(markdown) > 80:
                    combined_content.append(f"=== PAGE: {title} ({target}) ===\n{markdown[:3500]}")
        except Exception as e:
            print(f"Failed to scrape {target} with Firecrawl: {e}")

    return "\n\n".join(combined_content)


def _scrape_direct_fallback(domain):
    """Attempts a direct HTTP scrape of the homepage with optional TLS browser impersonation."""
    url = f"https://{domain}" if not domain.startswith(("http://", "https://")) else domain
    print(f"Attempting direct scrape fallback for {url}...")
    profiles = ["chrome124", "safari17_0", "chrome110"] if USE_CURL_CFFI else [None]

    for profile in profiles:
        try:
            if profile and USE_CURL_CFFI:
                response = curl_requests.get(
                    url,
                    impersonate=profile,
                    timeout=12,
                    headers={"Accept-Language": "en-US,en;q=0.9"},
                )
            else:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                response = requests.get(url, headers=headers, timeout=12)

            if response.status_code == 200:
                clean_text = extract_clean_page_text(response.text)
                if len(clean_text) > 80:
                    return clean_text
        except Exception:
            continue

    return ""


def _search_duckduckgo_fallback(company_name, domain):
    """Falls back to DuckDuckGo HTML search snippets when direct website scraping fails."""
    try:
        print(f"Attempting search fallback for {company_name} ({domain})...")
        search_query = f"{company_name} {domain} use cases solutions products software services"
        ddg_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(search_query)}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.get(ddg_url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            snippets = [s.get_text(strip=True) for s in soup.select(".result__snippet")[:6]]
            snippets_text = "\n".join(snippets).strip()
            if len(snippets_text) > 100:
                print(f"Found search snippets for {company_name}.")
                return snippets_text
    except Exception as e:
        print(f"Search fallback failed for {company_name}: {e}")

    return ""


def research_company(company_name, domain, firecrawl_api_key=""):
    """Researches a company via Firecrawl with automatic direct-scrape and search fallbacks."""
    if domain and firecrawl_api_key:
        text = map_and_scrape_website_firecrawl(domain, api_key=firecrawl_api_key)
        if text and len(text.strip()) > 100:
            print(f"Successfully scraped entire website for {company_name} ({len(text)} chars).")
            return text

    if domain:
        text = _scrape_direct_fallback(domain)
        if text:
            return text

    return _search_duckduckgo_fallback(company_name, domain)
