# -*- coding: utf-8 -*-
# config.py
# ===============================
# Global Configuration File (BioKG)
# ===============================

# ========== KEGG Configuration ==========
KEGG_BASE_URL = "https://rest.kegg.jp"

# Organism under study (KEGG organism code)
# eco : Escherichia coli
# hsa : Homo sapiens
ORGANISM = "hsa"

# Single pathway for debugging and testing parsing
TEST_PATHWAY = "hsa00010"   # Glycolysis / Gluconeogenesis


# ========== Neo4j Configuration ==========
NEO4J_URI = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345678"

# ========== PubMed Configuration ==========
PUBMED_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
PUBMED_ESEARCH_URL = PUBMED_BASE_URL + "esearch.fcgi"
PUBMED_EFETCH_URL = PUBMED_BASE_URL + "efetch.fcgi"
PUBMED_TOOL_EMAIL = "your.email@example.com" # Replace with your email
