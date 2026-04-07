"""
00_acquire_gleif.py
-------------------
Fetches Mexican legal entities and their corporate relationships from the
GLEIF (Global Legal Entity Identifier Foundation) API.

Two outputs:
  1. data/source/gleif_mx_entities.json   -- All active MX LEI records
  2. data/source/gleif_relationships.json  -- Parent-child edges for connected groups

The GLEIF API is open access, no authentication required.
Pagination: max 200 records per page, 1-based page numbering.
Parent/child endpoints return 404 when no relationship exists (not empty).
"""

import json
import time
import logging
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "https://api.gleif.org/api/v1/lei-records"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "source"
PAGE_SIZE = 200
REQUEST_DELAY = 0.3  # seconds between requests -- respectful pacing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def fetch_page(page_number: int) -> dict:
    """Fetch one page of active Mexican LEI records."""
    params = {
        "filter[entity.legalAddress.country]": "MX",
        "filter[entity.status]": "ACTIVE",
        "page[size]": PAGE_SIZE,
        "page[number]": page_number,
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_relationship(lei: str, rel_type: str) -> dict | None:
    """
    Fetch a relationship endpoint for a given LEI.
    rel_type: 'direct-parent', 'ultimate-parent', 'direct-children',
              'direct-child-relationships'
    Returns the JSON response or None if 404 (no relationship).
    """
    url = f"{BASE_URL}/{lei}/{rel_type}"
    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Extract helpers
# ---------------------------------------------------------------------------
def extract_entity(record: dict) -> dict:
    """Pull the fields we care about from a GLEIF lei-record."""
    attrs = record["attributes"]
    entity = attrs["entity"]
    legal_addr = entity.get("legalAddress", {})
    return {
        "lei": attrs["lei"],
        "legal_name": entity["legalName"]["name"],
        "status": entity["status"],
        "jurisdiction": entity.get("jurisdiction", ""),
        "registered_as": entity.get("registeredAs", ""),  # often RFC
        "legal_form_id": entity.get("legalForm", {}).get("id", ""),
        "creation_date": entity.get("creationDate", ""),
        "address_city": legal_addr.get("city", ""),
        "address_region": legal_addr.get("region", ""),  # ISO 3166-2 (MX-PUE, etc.)
        "address_country": legal_addr.get("country", ""),
        "address_postal": legal_addr.get("postalCode", ""),
    }


def extract_relationship_edge(rel_record: dict) -> dict:
    """Pull edge info from a Level 2 relationship record."""
    attrs = rel_record["attributes"]
    relationship = attrs["relationship"]
    return {
        "child_lei": relationship["startNode"]["id"],
        "parent_lei": relationship["endNode"]["id"],
        "rel_type": relationship["type"],  # IS_DIRECTLY_CONSOLIDATED_BY
        "rel_status": relationship["status"],
        "valid_from": attrs.get("validFrom", ""),
        "valid_to": attrs.get("validTo", ""),
    }


# ---------------------------------------------------------------------------
# Main acquisition
# ---------------------------------------------------------------------------
def acquire_entities() -> list[dict]:
    """Fetch all active Mexican LEI records, paginated."""
    first_page = fetch_page(1)
    total = first_page["meta"]["pagination"]["total"]
    last_page = first_page["meta"]["pagination"]["lastPage"]
    log.info(f"Total active MX entities: {total} across {last_page} pages")

    entities = [extract_entity(r) for r in first_page["data"]]
    log.info(f"Page 1/{last_page} -- {len(entities)} entities")

    for page_num in range(2, last_page + 1):
        time.sleep(REQUEST_DELAY)
        page_data = fetch_page(page_num)
        batch = [extract_entity(r) for r in page_data["data"]]
        entities.extend(batch)
        if page_num % 5 == 0 or page_num == last_page:
            log.info(f"Page {page_num}/{last_page} -- {len(entities)} entities total")

    return entities


def find_connected_groups(entities: list[dict]) -> list[dict]:
    """
    For each entity, check if it has a parent. Collect all parent-child edges.

    Strategy: instead of checking all 7000+ entities (slow), we check entities
    belonging to known financial groups first, then sample the rest.
    """
    # Known Mexican financial group keywords -- these are most likely to have
    # parent-child relationships in GLEIF
    GROUP_KEYWORDS = [
        "BBVA", "BANAMEX", "BANORTE", "SANTANDER", "HSBC", "SCOTIABANK",
        "INBURSA", "BANREGIO", "AZTECA", "COMPARTAMOS", "GENWORTH",
        "CITIGROUP", "CITI", "CREDIT SUISSE", "MORGAN", "GOLDMAN",
        "DEUTSCHE", "BARCLAYS", "GNP", "METLIFE", "MAPFRE", "AXA",
        "ZURICH", "ALLIANZ", "FEMSA", "BIMBO", "CEMEX", "AMERICA MOVIL",
        "GRUPO FINANCIERO", "GRUPO MEXICO", "TELEVISA", "ALFA",
    ]

    # Prioritize entities that match financial group keywords
    priority_leis = []
    other_leis = []
    for e in entities:
        name_upper = e["legal_name"].upper()
        if any(kw in name_upper for kw in GROUP_KEYWORDS):
            priority_leis.append(e["lei"])
        else:
            other_leis.append(e["lei"])

    log.info(
        f"Relationship scan: {len(priority_leis)} priority entities, "
        f"{len(other_leis)} others"
    )

    edges = []
    entities_with_parent = set()

    # Check priority entities for parent relationships
    for i, lei in enumerate(priority_leis):
        time.sleep(REQUEST_DELAY)
        parent_data = fetch_relationship(lei, "direct-parent")
        if parent_data and "data" in parent_data:
            parent_lei = parent_data["data"]["attributes"]["lei"]
            entities_with_parent.add(lei)
            log.info(
                f"  [{i+1}/{len(priority_leis)}] {lei} -> parent {parent_lei}"
            )

            # Get the detailed relationship edges from the parent
            time.sleep(REQUEST_DELAY)
            parent_children = fetch_relationship(
                parent_lei, "direct-child-relationships"
            )
            if parent_children and "data" in parent_children:
                for rel in parent_children["data"]:
                    edges.append(extract_relationship_edge(rel))
        else:
            if (i + 1) % 20 == 0:
                log.info(f"  [{i+1}/{len(priority_leis)}] scanning...")

    # Deduplicate edges
    seen = set()
    unique_edges = []
    for edge in edges:
        key = (edge["child_lei"], edge["parent_lei"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(edge)

    log.info(f"Found {len(unique_edges)} unique parent-child edges")
    return unique_edges


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Fetch all MX entities
    log.info("=" * 60)
    log.info("Step 1: Fetching all active Mexican LEI records")
    log.info("=" * 60)
    entities = acquire_entities()

    entities_path = OUTPUT_DIR / "gleif_mx_entities.json"
    with open(entities_path, "w", encoding="utf-8") as f:
        json.dump(entities, f, ensure_ascii=False, indent=2)
    log.info(f"Saved {len(entities)} entities to {entities_path}")

    # Step 2: Find connected groups
    log.info("=" * 60)
    log.info("Step 2: Scanning for parent-child relationships")
    log.info("=" * 60)
    relationships = find_connected_groups(entities)

    rels_path = OUTPUT_DIR / "gleif_relationships.json"
    with open(rels_path, "w", encoding="utf-8") as f:
        json.dump(relationships, f, ensure_ascii=False, indent=2)
    log.info(f"Saved {len(relationships)} relationships to {rels_path}")

    # Summary
    log.info("=" * 60)
    log.info("Done.")
    log.info(f"  Entities:      {len(entities)}")
    log.info(f"  Relationships: {len(relationships)}")
    log.info(f"  Output dir:    {OUTPUT_DIR}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
