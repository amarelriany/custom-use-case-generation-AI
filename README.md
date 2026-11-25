# AI B2B Lead Research & Personalization Agent

An **AI-powered Python agent pipeline** that autonomously researches prospect websites and uses **Google Gemini** to generate retrieval-grounded, 1-sentence B2B outreach lines at scale.

Designed as a production-minded LLM workflow, it pairs multi-tier live web retrieval (**Firecrawl** + resilient scraping fallbacks) with structured prompt engineering, hallucination guardrails, and cost-saving inference caching.

**Tech Stack:** Python · Google Gemini API (LLM) · Firecrawl API · BeautifulSoup · `curl_cffi`

---

## How It Works

```text
Input Lead CSV
      │
      ├──► Suppression Check (skips contacts in Already-contacted.csv)
      ├──► Resume Check (skips leads already saved in *_with_lines.csv)
      ├──► Domain Cache (reuses LLM output / skip decision across contacts at the same company)
      │
      ▼
Multi-Tier Web Retrieval (scraper.py)
  1. Firecrawl /v1/map + /v1/scrape  ──► Scores & retrieves high-intent pages (use cases, solutions, products, case studies)
  2. Direct TLS-Impersonated Scrape  ──► curl_cffi / requests + BeautifulSoup noise stripping (fallback)
  3. DuckDuckGo Search Snippets      ──► Web snippet retrieval when direct scraping is blocked (fallback)
      │
      ▼
Grounded LLM Generation (generator.py + system_prompt.txt)
  • Retrieval-grounded generation strictly anchored in scraped website context
  • Prioritized reasoning strategy with few-shot benchmark guidance
  • Guardrail abstention routing: returns SKIP (non-B2B) or N/A (insufficient context)
  • Streams each enriched row immediately to *_with_lines.csv
```

---

## AI & Engineering Highlights

- **Retrieval-Grounded LLM Generation**: Maps and ranks each prospect's website to extract up to 4 high-signal pages (up to 3,500 chars/page), feeding dense, relevant markdown context into Gemini to prevent hallucinated product claims.
- **Prompt Engineering & Hallucination Guardrails**: Uses a decoupled system prompt ([`system_prompt.txt`](system_prompt.txt)) featuring a two-tier reasoning hierarchy (automation use-case extraction with a strategic-initiative fallback), few-shot benchmark examples, strict single-sentence formatting constraints, and explicit `SKIP` / `N/A` abstention rules.
- **3-Tier Retrieval Resilience**: Automatically degrades from Firecrawl to browser TLS-impersonated scraping (`curl_cffi`) and DuckDuckGo HTML snippets when sites block automated requests or when Firecrawl is not configured.
- **Inference Cost Optimization (Domain-Level Caching)**: Reuses cached LLM outputs and `SKIP` decisions across multiple contacts at the same company domain, cutting token usage, scraping calls, and latency on multi-contact accounts.
- **Crash-Safe Resumability & Failover**: Flushes each generated row to disk immediately, resumes interrupted batch runs without reprocessing completed leads, and supports automatic failover to a backup Gemini API key.
- **Suppression & Flexible Schema Handling**: Filters out previously contacted emails via `Already-contacted.csv` and normalizes varying CRM/lead export column headers automatically.

---

## Example Output

Given an input CSV like [`examples/sample_leads.csv`](examples/sample_leads.csv), the pipeline produces an enriched CSV ([`examples/sample_leads_with_lines.csv`](examples/sample_leads_with_lines.csv)) with a `Personalized Line` column:

| Company | Domain | Generated `Personalized Line` |
| --- | --- | --- |
| DocuFlow | `docuflow.example.com` | *DocuFlow could use SignalPulse AI to find finance and accounting teams hiring invoice clerks to manually extract line-item data from PDF receipts and purchase orders.* |
| KoreCare | `korecare.example.com` | *KoreCare could use SignalPulse AI to find healthcare operations teams hiring intake coordinators to manually verify patient insurance eligibility and pre-authorizations.* |
| CloudForge | `cloudforge.example.com` | *CloudForge could use SignalPulse AI to find enterprise IT teams hiring DevOps engineers to migrate on-premise infrastructure to Google Cloud.* |

*(Sample data uses fictional companies and placeholder domains.)*

---

## Project Structure

```text
.
├── agent.py                          # CLI entry point, CSV I/O, caching & resumable checkpointing
├── scraper.py                        # 3-tier website research (Firecrawl, direct scrape, DuckDuckGo)
├── generator.py                      # Gemini client with key failover & line generation
├── system_prompt.txt                 # Customizable LLM prompt & copywriting rules
├── requirements.txt                  # Python dependencies
├── .env.example                      # Environment variable template
├── .gitignore                        # Excludes .env and real lead CSVs from Git
├── Leads/                            # Drop your input lead CSVs here (gitignored)
└── examples/
    ├── sample_leads.csv              # Fictional input lead list
    ├── sample_leads_with_lines.csv   # Sample enriched output
    └── Already-contacted.example.csv # Sample suppression list format
```

---

## Quick Start

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/amarelriany/custom-use-case-generation-AI.git
cd custom-use-case-generation-AI

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and add your API keys:

```bash
cp .env.example .env
```

| Variable | Required | Description |
| --- | --- | --- |
| `GEMINI_API_KEY` | Yes | Google Gemini API key used for line generation |
| `GEMINI_BACKUP_API_KEY` | No | Optional fallback Gemini key if the primary key fails |
| `FIRECRAWL_API_KEY` | No | Firecrawl API key for multi-page site mapping/scraping (falls back to direct scraping if omitted) |
| `GEMINI_MODEL` | No | Gemini model identifier (default: `models/gemini-3.7-flash`) |
| `SYSTEM_PROMPT_FILE` | No | Path to custom prompt file (default: `system_prompt.txt`) |

### 3. Customize the Outreach Prompt

Edit [`system_prompt.txt`](system_prompt.txt) to replace the sample product (`SignalPulse AI`) and value proposition with your own B2B offer, tone rules, and benchmark examples.

### 4. Run the Pipeline

```bash
# Process all CSV files placed inside Leads/
python agent.py

# Process a specific CSV file (writes <name>_with_lines.csv alongside it)
python agent.py examples/sample_leads.csv

# Process a specific CSV file with a custom output path
python agent.py Leads/prospects.csv Leads/prospects_enriched.csv
```

To suppress previously contacted leads, place an `Already-contacted.csv` file (with an `Email` column) in the project root or inside `Leads/`—see [`examples/Already-contacted.example.csv`](examples/Already-contacted.example.csv).

---

## Privacy & Security

- API credentials are loaded exclusively from environment variables (`.env` is gitignored).
- Real prospect lists (`Leads/*.csv`, `*_with_lines.csv`) and suppression lists (`Already-contacted.csv`) are excluded in `.gitignore` to prevent accidentally committing PII.
