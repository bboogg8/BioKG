# -*- coding: utf-8 -*-
# pubmed_api.py
# ==========================================
# PubMed API Interface Module
# Communicates with NCBI E-utilities via HTTP
# ==========================================
import time
import requests
import xml.etree.ElementTree as ET

try:
    from BioKG.config.config import (
        PUBMED_BASE_URL,
        PUBMED_ESEARCH_URL,
        PUBMED_EFETCH_URL,
        PUBMED_TOOL_EMAIL,
    )
except ModuleNotFoundError:
    from config.config import (
        PUBMED_BASE_URL,
        PUBMED_ESEARCH_URL,
        PUBMED_EFETCH_URL,
        PUBMED_TOOL_EMAIL,
    )

def search_pubmed(term, retmax=1000):
    """
    Searches PubMed for articles matching the given term.
    Returns a list of PubMed IDs (PMIDs).
    """
    params = {
        "db": "pubmed",
        "term": term,
        "retmax": retmax,
        "field": "all",
        "tool": "BioKG",
        "email": PUBMED_TOOL_EMAIL,
    }
    try:
        response = requests.get(PUBMED_ESEARCH_URL, params=params)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        pmid_list = [id_element.text for id_element in root.findall("IdList/Id")]
        return pmid_list
    except Exception as e:
        print(f"? Failed to search PubMed: {e}")
        return []

def fetch_abstract(pmid):
    """
    Fetches the abstract for a given PubMed ID (PMID).
    Returns the abstract text or None if not found/error.
    """
    params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml",
        "tool": "BioKG",
        "email": PUBMED_TOOL_EMAIL,
    }
    try:
        # Add delay to avoid triggering PubMed's request limit
        time.sleep(0.1)
        response = requests.get(PUBMED_EFETCH_URL, params=params)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        abstract_nodes = root.findall(".//Abstract/AbstractText")
        abstract_parts = []

        for node in abstract_nodes:
            label = node.attrib.get("Label")
            text = "".join(node.itertext()).strip()
            if not text:
                continue
            abstract_parts.append(f"{label}: {text}" if label else text)

        if abstract_parts:
            return " ".join(abstract_parts)
        return None
    except Exception as e:
        print(f"? Failed to fetch abstract (PMID: {pmid}): {e}")
        return None
