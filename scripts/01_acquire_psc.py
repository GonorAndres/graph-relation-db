"""
01_acquire_psc.py
-----------------
Extracts person-to-company ownership data from the Open Ownership BODS
Datasette (no download, no registration).

Strategy:
  1. Batch-query common British full names to find persons controlling 2+ companies
  2. For each person found, get their full company list + birth date
  3. Save persons, companies, and person→company relationships

The Datasette has 12M person records but NO custom indexes. Only fullname-based
queries with GROUP BY work within the 30-second timeout. Queries on
familyname alone or declarationsubject (company ID) time out.

Output:
  data/source/psc_persons.json       -- Persons with names + birth months
  data/source/psc_companies.json     -- Company IDs found
  data/source/psc_relationships.json -- Person→Company edges
"""

import json
import time
import logging
import urllib.parse
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATASETTE_BASE = "https://bods-data-datasette.openownership.org/uk_version_0_4.json"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "source"
REQUEST_DELAY = 1.5  # respectful pacing for free public service
MIN_COMPANIES = 2    # minimum companies to be considered "interesting"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Full names to search -- common British Title + First + Last combinations
# These are the patterns that exist in UK PSC data
SEED_NAMES = [
    # Smiths
    "Mr David Smith", "Mr John Smith", "Mr James Smith", "Mr Michael Smith",
    "Mr Andrew Smith", "Mr Richard Smith", "Mr Peter Smith", "Mr Robert Smith",
    "Mr Mark Smith", "Mr Paul Smith", "Mr Stephen Smith", "Mr Chris Smith",
    "Mrs Sarah Smith", "Mrs Jane Smith", "Ms Emma Smith",
    # Jones
    "Mr David Jones", "Mr John Jones", "Mr Michael Jones", "Mr Andrew Jones",
    "Mr Richard Jones", "Mr Mark Jones", "Mr Paul Jones",
    # Taylor
    "Mr David Taylor", "Mr John Taylor", "Mr James Taylor", "Mr Michael Taylor",
    "Mr Andrew Taylor", "Mr Richard Taylor", "Mr Mark Taylor",
    # Brown
    "Mr David Brown", "Mr John Brown", "Mr James Brown", "Mr Michael Brown",
    "Mr Andrew Brown", "Mr Mark Brown",
    # Williams
    "Mr David Williams", "Mr John Williams", "Mr Michael Williams",
    "Mr Andrew Williams", "Mr Mark Williams",
    # Wilson
    "Mr David Wilson", "Mr John Wilson", "Mr Michael Wilson", "Mr Andrew Wilson",
    # Johnson
    "Mr David Johnson", "Mr John Johnson", "Mr Michael Johnson",
    # Other common surnames
    "Mr David Roberts", "Mr John Roberts", "Mr David Evans", "Mr John Evans",
    "Mr David Robinson", "Mr David Wright", "Mr David Thompson",
    "Mr David Walker", "Mr David White", "Mr David Hall",
    "Mr David Wood", "Mr David Jackson", "Mr David Clarke",
    "Mr David Green", "Mr David King", "Mr David Harris",
    "Mr David Lewis", "Mr David Turner", "Mr David Hill",
    "Mr David Scott", "Mr David Cooper", "Mr David Morris",
    "Mr David Ward", "Mr David Moore", "Mr David Clark",
    "Mr David Baker", "Mr David Martin", "Mr David Morgan",
    # South Asian names (common in UK PSC data)
    "Mr Ashok Patel", "Mr Manoj Patel", "Mr Raj Patel", "Mr Rajesh Patel",
    "Mr Amit Patel", "Mr Suresh Patel", "Mr Bharat Patel",
    "Mr Mohammed Khan", "Mr Mohammed Ali", "Mr Rajesh Shah",
    "Mr Ajay Kumar", "Mr Sanjay Patel", "Mr Nilesh Patel",
    "Mr Mohammed Ahmed", "Mr Abdul Khan",
    # Additional first names with common surnames
    "Mr Thomas Smith", "Mr Daniel Smith", "Mr Matthew Smith",
    "Mr Christopher Jones", "Mr Daniel Jones", "Mr Thomas Jones",
    "Mr Christopher Taylor", "Mr Daniel Taylor",
    "Mr Christopher Brown", "Mr Daniel Brown",
    "Mr Thomas Williams", "Mr Daniel Williams",
    "Mr Thomas Wilson", "Mr Christopher Wilson",
    # Women controllers
    "Mrs Sarah Jones", "Mrs Jane Brown", "Mrs Susan Taylor",
    "Ms Emma Jones", "Ms Claire Smith", "Mrs Julie Smith",
    "Mrs Helen Taylor", "Mrs Karen Wilson",
]


# ---------------------------------------------------------------------------
# Datasette query helper
# ---------------------------------------------------------------------------
def query_datasette(sql: str, retries: int = 2) -> list[dict]:
    """Execute a SQL query against the BODS Datasette."""
    params = {"sql": sql, "_shape": "array"}
    url = f"{DATASETTE_BASE}?{urllib.parse.urlencode(params)}"

    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=90)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 400:
                # Likely a timeout
                return []
            else:
                log.warning(f"HTTP {resp.status_code} on attempt {attempt+1}")
        except requests.exceptions.Timeout:
            log.warning(f"Timeout on attempt {attempt+1}")
        time.sleep(REQUEST_DELAY * (attempt + 1))

    return []


# ---------------------------------------------------------------------------
# Phase 1: Batch-find multi-company controllers
# ---------------------------------------------------------------------------
def find_controllers(names: list[str]) -> list[dict]:
    """
    Find persons in the given name list who control 2+ companies.
    Sends names in batches of ~40 to stay within URL length limits.
    """
    all_results = []
    batch_size = 40

    for batch_start in range(0, len(names), batch_size):
        batch = names[batch_start:batch_start + batch_size]
        names_sql = ", ".join(f"'{n}'" for n in batch)

        sql = f"""
        SELECT n.fullname, p.recorddetails_birthdate,
               COUNT(DISTINCT p.declarationsubject) as company_count
        FROM person_recordDetails_names n
        JOIN person_statement p ON n._link_person_statement = p._link
        WHERE n.fullname IN ({names_sql})
        GROUP BY n.fullname, p.recorddetails_birthdate
        HAVING COUNT(DISTINCT p.declarationsubject) >= {MIN_COMPANIES}
        ORDER BY company_count DESC
        LIMIT 200
        """
        time.sleep(REQUEST_DELAY)
        results = query_datasette(sql)
        all_results.extend(results)

        batch_num = batch_start // batch_size + 1
        total_batches = (len(names) + batch_size - 1) // batch_size
        log.info(
            f"  Batch {batch_num}/{total_batches}: "
            f"{len(results)} controllers found (running total: {len(all_results)})"
        )

    # Deduplicate by (fullname, birthdate)
    seen = set()
    unique = []
    for r in all_results:
        key = (r["fullname"], r.get("recorddetails_birthdate", ""))
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return sorted(unique, key=lambda x: x["company_count"], reverse=True)


# ---------------------------------------------------------------------------
# Phase 2: Get company lists for each controller
# ---------------------------------------------------------------------------
def get_person_companies(fullname: str, birthdate: str) -> list[dict]:
    """Get all companies controlled by a specific person."""
    bd_clause = f"AND p.recorddetails_birthdate = '{birthdate}'" if birthdate else ""
    sql = f"""
    SELECT n.fullname, p.recorddetails_birthdate,
           p.declarationsubject, p.recordid
    FROM person_recordDetails_names n
    JOIN person_statement p ON n._link_person_statement = p._link
    WHERE n.fullname = '{fullname}' {bd_clause}
    LIMIT 100
    """
    time.sleep(REQUEST_DELAY)
    return query_datasette(sql)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Phase 1: Discover controllers
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("Phase 1: Finding multi-company controllers")
    log.info(f"  Searching {len(SEED_NAMES)} name variants")
    log.info("=" * 60)

    controllers = find_controllers(SEED_NAMES)
    log.info(f"Found {len(controllers)} unique multi-company controllers")

    if not controllers:
        log.error("No controllers found. Check Datasette connectivity.")
        return

    # Show top controllers
    for c in controllers[:10]:
        log.info(
            f"  {c['fullname']} (born {c.get('recorddetails_birthdate', '?')}): "
            f"{c['company_count']} companies"
        )

    # ------------------------------------------------------------------
    # Phase 2: Get company lists
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("Phase 2: Fetching company lists for each controller")
    log.info("=" * 60)

    persons = []
    relationships = []
    all_company_ids = set()

    for i, ctrl in enumerate(controllers):
        fullname = ctrl["fullname"]
        birthdate = ctrl.get("recorddetails_birthdate", "")

        companies = get_person_companies(fullname, birthdate)
        if not companies:
            continue

        person_id = f"PSC-{len(persons)+1:05d}"
        persons.append({
            "person_id": person_id,
            "fullname": fullname,
            "birthdate": birthdate,
            "company_count": ctrl["company_count"],
        })

        for comp in companies:
            company_ref = comp.get("declarationsubject", "")
            if company_ref:
                all_company_ids.add(company_ref)
                relationships.append({
                    "person_id": person_id,
                    "fullname": fullname,
                    "company_ref": company_ref,
                })

        if (i + 1) % 20 == 0 or i + 1 == len(controllers):
            log.info(
                f"  [{i+1}/{len(controllers)}] "
                f"{len(persons)} persons, {len(relationships)} edges, "
                f"{len(all_company_ids)} companies"
            )

    # ------------------------------------------------------------------
    # Phase 3: Build company list
    # ------------------------------------------------------------------
    companies_list = []
    for comp_ref in sorted(all_company_ids):
        parts = comp_ref.split("-")
        company_number = parts[-1] if len(parts) >= 3 else comp_ref
        companies_list.append({
            "company_ref": comp_ref,
            "company_number": company_number,
            "source": "BODS_Datasette",
        })

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("Saving outputs")
    log.info("=" * 60)

    for data, filename in [
        (persons, "psc_persons.json"),
        (companies_list, "psc_companies.json"),
        (relationships, "psc_relationships.json"),
    ]:
        path = OUTPUT_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info(f"Saved {len(data)} records to {path}")

    # Summary
    log.info("=" * 60)
    log.info("Done.")
    log.info(f"  Persons:       {len(persons)}")
    log.info(f"  Companies:     {len(companies_list)}")
    log.info(f"  Relationships: {len(relationships)}")

    # Connectivity stats
    companies_with_multiple = sum(
        1 for c in all_company_ids
        if sum(1 for r in relationships if r["company_ref"] == c) >= 2
    )
    log.info(f"  Companies with 2+ controllers: {companies_with_multiple}")
    log.info(f"  Output dir:    {OUTPUT_DIR}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
