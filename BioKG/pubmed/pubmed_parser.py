# -*- coding: utf-8 -*-
# pubmed_parser.py
import spacy
import scispacy
import re
from thefuzz import process, fuzz
from .pubmed_api import fetch_abstract

from .pubmed_writer import write_publication

# Load model
try:
    # bionlp13cg is recommended for its sensitivity in recognizing genes and proteins
    nlp = spacy.load("en_ner_bionlp13cg_md")
except:
    print("Error: Please install the model first: pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bionlp13cg_md-0.5.4.tar.gz")

class PubMedParser:
    def __init__(self, synonym_dict=None):
        """
        synonym_dict: { "LDHA": "1.1.1.27", "GAPDH": "1.2.1.12" ... }
        """
        self.synonym_dict = synonym_dict if synonym_dict else {}
        # Pre-cache all keys for fuzzy matching acceleration
        self.dict_keys = list(self.synonym_dict.keys())

    def _normalize(self, text):
        """
        Normalization processing: uppercase, remove hyphens, underscores, and spaces
        Example: "LDH-A" -> "LDHA"
        """
        return re.sub(r"[\W_]+", "", text).upper()

    def _is_valid_entity(self, mention):
        """
        Data cleaning firewall: filter out noisy entities
        """
        m_upper = mention.upper()
        
        # 1. Filter common non-biomedical interfering words
        noise_patterns = [
            r'DOI[:/]', r'PMC\d+', r'HTTP', r'HTTPS', r'COPYRIGHT', 
            r'PUBLISHED', r'PUBLISHER', r'FIG', r'TABLE', r'AUTHOR',
            r'LICENSE', r'ORCID'
        ]
        for pattern in noise_patterns:
            if re.search(pattern, m_upper):
                return False
        
        # 2. Length filtering: too short (e.g., "A", "2") or too long (may be sentence fragments)
        if len(mention) < 3 or len(mention) > 100:
            return False
            
        # 3. Filter pure numbers or pure special symbols
        if mention.isdigit() or not re.search(r'[A-Za-z]', mention):
            return False
            
        return True

    def _smart_match(self, mention):
        """
        Three-level matching strategy: Exact -> Normalized -> Fuzzy
        """
        mention_upper = mention.upper()
        mention_norm = self._normalize(mention)

        # Level 1: Exact match
        if mention_upper in self.synonym_dict:
            return self.synonym_dict[mention_upper], 0.95, "Exact"

        # Level 2: Normalized match
        if mention_norm in self.synonym_dict:
             return self.synonym_dict[mention_norm], 0.90, "Normalized"
        
        # Level 3: Fuzzy matching (only performed if dictionary is not empty)
        if self.dict_keys:
            best_match, score = process.extractOne(mention_upper, self.dict_keys, scorer=fuzz.token_sort_ratio)
            if score >= 90:
                return self.synonym_dict[best_match], 0.85, f"Fuzzy({score}%)"
            elif score >= 80:
                return self.synonym_dict[best_match], 0.75, f"Fuzzy({score}%)"
            
        return None, 0.0, None

    def extract_entities_with_ner(self, text):
        if not text: return []
        doc = nlp(text)
        results = []
        
        # --- A. Regex extraction (direct extraction of EC numbers) ---
        regex_ecs = list(set(re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", text)))
        for ec in regex_ecs:
            results.append({
                "type": "EC_DIRECT",
                "id": ec,
                "mention": ec,
                "confidence": 1.0,
                "method": "Regex"
            })
        
        # --- B. NER model extraction + smart alignment ---
        for ent in doc.ents:
            # Only process gene/protein entities
            if ent.label_ == "GENE_OR_GENE_PRODUCT":
                mention = ent.text.strip()
                
                # --- New: Noise filtering logic ---
                if not self._is_valid_entity(mention):
                    continue
                
                # Call smart matching function
                ec_id, conf, method = self._smart_match(mention)

                if ec_id:
                    results.append({
                        "type": "ENZYME_NAME",
                        "id": ec_id,
                        "mention": mention,
                        "confidence": conf,
                        "method": method
                    })
                else:
                    # Only include candidates that pass filtering and are not matched
                    results.append({
                        "type": "CANDIDATE",
                        "id": None,
                        "mention": mention,
                        "confidence": 0.4,
                        "method": "Unmatched"
                    })
        
        # --- C. Deduplication logic ---
        unique_results = {}
        for res in results:
            # For candidate entities, use their content as Key; for successfully matched entities, use their ID
            key = res['id'] if res['id'] else f"CAND_{res['mention'].upper()}"
            
            if key not in unique_results:
                unique_results[key] = res
            else:
                # Keep the result with higher confidence
                if res['confidence'] > unique_results[key]['confidence']:
                    unique_results[key] = res
        
        return list(unique_results.values())
