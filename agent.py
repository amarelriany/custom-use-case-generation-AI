import csv
import glob
import os
import re
import sys
import time
import warnings

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from generator import LineGenerator
from scraper import research_company

# Configuration (loaded from environment variables or .env file)
PRIMARY_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
BACKUP_GEMINI_KEY = os.getenv("GEMINI_BACKUP_API_KEY", "").strip()
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-3.7-flash").strip()
PROMPT_FILE = os.getenv("SYSTEM_PROMPT_FILE", "system_prompt.txt").strip()


def extract_domain(email):
    """Extracts the domain part from an email address."""
    if not email or "@" not in email:
        return ""
    parts = email.split("@")
    if len(parts) > 1:
        domain = parts[1].strip().lower()
        return domain.split("/")[0]
    return ""


def normalize_website_key(website, domain, company):
    """Generates a normalized cache key for a company/website."""
    for candidate in (domain, website):
        if candidate:
            clean = candidate.strip().lower()
            clean = re.sub(r"^https?://", "", clean)
            clean = re.sub(r"^www\.", "", clean)
            clean = clean.split("/")[0].strip()
            if clean:
                return clean
    if company:
        return company.strip().lower()
    return ""


def load_contacted_emails():
    """Loads previously contacted emails from Already-contacted.csv if present."""
    contacted = set()
    candidate_files = [
        "Already-contacted.csv",
        "already-contacted.csv",
        "Already_contacted.csv",
        os.path.join("Leads", "Already-contacted.csv"),
    ]
    email_columns = ("Email", "email", "Work Email", "Work Email (VALID)", "work_email", "contact")

    for cf in candidate_files:
        if os.path.exists(cf):
            try:
                with open(cf, mode="r", encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        for col in email_columns:
                            if row.get(col):
                                em = row[col].strip().lower()
                                if em:
                                    contacted.add(em)
                print(f"Loaded {len(contacted)} already contacted email(s) from {cf}.")
                break
            except Exception as e:
                print(f"Warning: Could not read {cf}: {e}")
    return contacted


def get_lead_identifier(row):
    """Returns a normalized unique identifier string for deduplicating/resuming a lead row."""
    email = (
        row.get("Email")
        or row.get("Work Email")
        or row.get("Work Email (VALID)")
        or row.get("Work EmailWork Email")
        or row.get("contact")
        or row.get("email")
        or ""
    ).strip().lower()
    if email and "@" in email:
        return f"email:{email}"

    linkedin = (
        row.get("LinkedIn")
        or row.get("LinkedIn URL")
        or row.get("Contact LinkedIn URL")
        or row.get("linkedin")
        or ""
    ).strip().lower()
    if linkedin:
        clean_li = re.sub(r"https?://(www\.)?", "", linkedin).rstrip("/")
        return f"li:{clean_li}"

    first = (row.get("Clean First Name") or row.get("First Name") or row.get("first_name") or row.get("First") or "").strip().lower()
    last = (row.get("Last Name") or row.get("last_name") or row.get("Last") or "").strip().lower()
    company = (
        row.get("Clean Company Name")
        or row.get("Company")
        or row.get("companyName")
        or row.get("company_name")
        or row.get("Company Name")
        or ""
    ).strip().lower()
    if company:
        return f"name_co:{first}:{last}:{company}"

    return ""


def _load_existing_progress(output_path, default_fieldnames):
    """Loads previously written output rows so interrupted runs resume cleanly."""
    fieldnames = list(default_fieldnames)
    processed_ids = set()
    line_cache = {}
    resuming = False

    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        try:
            with open(output_path, mode="r", encoding="utf-8-sig") as existing_file:
                existing_reader = csv.DictReader(existing_file)
                if existing_reader.fieldnames:
                    fieldnames = list(existing_reader.fieldnames)
                    if "Personalized Line" not in fieldnames:
                        fieldnames.append("Personalized Line")

                for r in existing_reader:
                    rid = get_lead_identifier(r)
                    if rid:
                        processed_ids.add(rid)

                    r_co = (
                        r.get("Clean Company Name")
                        or r.get("Company")
                        or r.get("companyName")
                        or r.get("company_name")
                        or r.get("Company Name")
                        or ""
                    ).strip()
                    r_domain = (
                        r.get("Company Domain")
                        or r.get("companyDomain")
                        or r.get("company_domain")
                        or r.get("Domain")
                        or r.get("domain")
                        or ""
                    ).strip()
                    r_web = r.get("Website") or r.get("website") or r.get("URL") or r.get("url") or r.get("Company Website") or ""
                    r_line = r.get("Personalized Line", "").strip()

                    if r_line and r_line not in ("", "N/A", "SKIP", "Could not generate line."):
                        ck = normalize_website_key(r_web, r_domain, r_co)
                        if ck:
                            line_cache[ck] = {"status": "SUCCESS", "line": r_line}

            if processed_ids:
                resuming = True
                print(f"Resuming previous run: Found {len(processed_ids)} already completed lead(s) in {output_path}.\n")
        except Exception as e:
            print(f"Warning: Could not read existing output file for resume: {e}")

    return fieldnames, processed_ids, line_cache, resuming


def process_file(input_path, output_path, generator):
    """Reads an input lead CSV, researches each company, and streams enriched rows to output_path."""
    print("\n=======================================================")
    print(f"Processing File: {input_path}")
    print(f"Output File:     {output_path}")
    print("=======================================================\n")

    contacted_emails = load_contacted_emails()

    with open(input_path, mode="r", encoding="utf-8-sig") as infile:
        reader = csv.DictReader(infile)
        rows = list(reader)
        raw_fieldnames = list(reader.fieldnames) if reader.fieldnames else []

    default_fieldnames = list(raw_fieldnames)
    if "Website" not in default_fieldnames and not any(f in default_fieldnames for f in ["website", "URL", "url", "Company Website"]):
        default_fieldnames.append("Website")
    if "Personalized Line" not in default_fieldnames:
        default_fieldnames.append("Personalized Line")

    fieldnames, processed_ids, line_cache, resuming = _load_existing_progress(output_path, default_fieldnames)

    file_mode = "a" if resuming else "w"
    with open(output_path, mode=file_mode, encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        if not resuming:
            writer.writeheader()

        total = len(rows)
        for idx, row in enumerate(rows, 1):
            full_name = (row.get("Full Name") or row.get("full_name") or row.get("Name") or row.get("name") or "").strip()
            first_name = (row.get("Clean First Name") or row.get("First Name") or row.get("first_name") or row.get("First") or "").strip()
            last_name = (row.get("Last Name") or row.get("last_name") or row.get("Last") or "").strip()
            if not first_name and full_name:
                parts = full_name.split(None, 1)
                first_name = parts[0]
                if len(parts) > 1 and not last_name:
                    last_name = parts[1]

            company = (
                row.get("Clean Company Name")
                or row.get("Company")
                or row.get("companyName")
                or row.get("company_name")
                or row.get("Company Name")
                or ""
            ).strip()
            email = (
                row.get("Email")
                or row.get("Work Email")
                or row.get("Work Email (VALID)")
                or row.get("Work EmailWork Email")
                or row.get("contact")
                or row.get("email")
                or ""
            ).strip()

            if email and email.lower() in contacted_emails:
                print(f"[{idx}/{total}] Skipping {company} ({first_name} {last_name}) - Email '{email}' is in Already-contacted list.\n")
                continue

            raw_domain = (
                row.get("Company Domain")
                or row.get("companyDomain")
                or row.get("company_domain")
                or row.get("sourceCompanyDomain")
                or row.get("Domain")
                or row.get("domain")
                or ""
            )
            domain = raw_domain.strip() if raw_domain else extract_domain(email)
            website = row.get("Website") or row.get("website") or row.get("URL") or row.get("url") or row.get("Company Website") or (f"https://{domain}" if domain else "")

            if not company:
                continue

            lead_id = get_lead_identifier(row)
            if lead_id and lead_id in processed_ids:
                print(f"[{idx}/{total}] Skipping {company} ({first_name} {last_name}) - Already completed in output file.")
                continue

            cache_key = normalize_website_key(website, domain, company)

            if cache_key and cache_key in line_cache:
                cached = line_cache[cache_key]
                if cached["status"] == "SKIP":
                    print(f"[{idx}/{total}] Skipping {company} ({first_name} {last_name}) - Reusing cached skip decision for website ({cache_key}).\n")
                    continue
                if cached["status"] == "SUCCESS":
                    line = cached["line"]
                    print(f"[{idx}/{total}] Reusing cached personalized line for {company} ({first_name} {last_name}) [{cache_key}]...")
                    print(f"  -> Line: {line} (Cached)\n")

                    if "Website" in fieldnames:
                        row["Website"] = website
                    row["Personalized Line"] = line

                    writer.writerow(row)
                    outfile.flush()
                    if lead_id:
                        processed_ids.add(lead_id)
                    continue

            print(f"[{idx}/{total}] Processing {company} ({first_name} {last_name})...")

            info = research_company(company, domain, firecrawl_api_key=FIRECRAWL_API_KEY)
            if not info or len(info.strip()) < 80:
                print(f"Skipping {company}: Insufficient research data to ground a personalized line.\n")
                if cache_key:
                    line_cache[cache_key] = {"status": "SKIP"}
                continue

            line = generator.generate(company, info)
            upper_line = line.strip().upper()
            if upper_line in ("SKIP", "N/A") or upper_line.startswith(("SKIP", "N/A")):
                print(f"Skipping {company} (Response: {line}).\n")
                if cache_key:
                    line_cache[cache_key] = {"status": "SKIP"}
                continue

            print(f"  -> Line: {line}\n")

            if cache_key:
                line_cache[cache_key] = {"status": "SUCCESS", "line": line}

            if "Website" in fieldnames:
                row["Website"] = website
            row["Personalized Line"] = line

            writer.writerow(row)
            outfile.flush()
            if lead_id:
                processed_ids.add(lead_id)

            time.sleep(0.5)

    print(f"\nFinished file: {input_path} -> Saved to: {output_path}")


def _is_processable_csv(path):
    """Returns True if the CSV path is an input lead list (not output or suppression list)."""
    name = os.path.basename(path).lower()
    if name.endswith("_with_lines.csv"):
        return False
    if name in ("already-contacted.csv", "already_contacted.csv"):
        return False
    return True


def get_target_files():
    """Detects target CSV files to process from CLI args or the Leads/ directory."""
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("-h", "--help"):
            print("Usage: python agent.py [input_csv_or_dir] [output_csv]")
            print("\nExamples:")
            print("  python agent.py                                  # Process all CSVs in Leads/")
            print("  python agent.py examples/sample_leads.csv        # Process a single CSV file")
            print("  python agent.py Leads/my_leads.csv out.csv       # Specify custom output path")
            sys.exit(0)
        if os.path.isdir(arg):
            files = sorted(glob.glob(os.path.join(arg, "*.csv")))
            return [f for f in files if _is_processable_csv(f)]
        if os.path.isfile(arg):
            return [arg]
        print(f"Error: Argument path '{arg}' does not exist.")
        sys.exit(1)

    leads_dir = "Leads" if os.path.exists("Leads") else ("leads" if os.path.exists("leads") else "")
    if leads_dir:
        files = sorted(glob.glob(os.path.join(leads_dir, "*.csv")))
        return [f for f in files if _is_processable_csv(f)]

    return []


def main():
    target_files = get_target_files()
    if not target_files:
        print("No input CSV files found in Leads/.")
        print("Place a CSV in Leads/ or pass a path explicitly, e.g.:")
        print("  python agent.py examples/sample_leads.csv")
        sys.exit(1)

    try:
        generator = LineGenerator(
            primary_api_key=PRIMARY_GEMINI_KEY,
            backup_api_key=BACKUP_GEMINI_KEY,
            model_name=GEMINI_MODEL,
            prompt_file=PROMPT_FILE,
        )
    except RuntimeError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    print(f"Found {len(target_files)} target file(s) to process: {target_files}")

    for input_file in target_files:
        dir_name = os.path.dirname(input_file)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(dir_name, f"{base_name}_with_lines.csv") if dir_name else f"{base_name}_with_lines.csv"

        if len(sys.argv) > 2 and len(target_files) == 1:
            output_file = sys.argv[2]

        process_file(input_file, output_file, generator)

    print("\nAll files processed successfully!")


if __name__ == "__main__":
    main()
