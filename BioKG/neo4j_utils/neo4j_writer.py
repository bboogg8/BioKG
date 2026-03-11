# -*- coding: utf-8 -*-
# neo4j_writer.py
"""
Neo4j Write Module
Responsible for creating nodes and relationships (does not include data acquisition and parsing)
"""

from .neo4j_conn import get_driver


# ========= Node Creation =========

def create_pathway(pathway_id: str, name: str = None):
    """
    Create Pathway node
    """
    with get_driver().session() as session:
        session.run(
            """
            MERGE (p:Pathway {id: $id})
            SET p.name = coalesce($name, p.name)
            """,
            id=pathway_id,
            name=name
        )


def create_enzyme(ec: str):
    """
    Create Enzyme (EC) node
    """
    with get_driver().session() as session:
        session.run(
            """
            MERGE (:Enzyme {ec: $ec})
            """,
            ec=ec
        )


def create_protein(uniprot_id: str, gene: str = None, name: str = None):
    """
    Create Protein node (reserved for future UniProt use)
    """
    with get_driver().session() as session:
        session.run(
            """
            MERGE (p:Protein {uniprot_id: $uid})
            SET
              p.gene = coalesce($gene, p.gene),
              p.name = coalesce($name, p.name)
            """,
            uid=uniprot_id,
            gene=gene,
            name=name
        )


# ========= Relationship Creation =========

def link_pathway_enzyme(pathway_id: str, ec: str):
    """
    (Pathway)-[:HAS_ENZYME]->(Enzyme)
    """
    with get_driver().session() as session:
        session.run(
            """
            MATCH (p:Pathway {id: $pid})
            MATCH (e:Enzyme {ec: $ec})
            MERGE (p)-[:HAS_ENZYME]->(e)
            """,
            pid=pathway_id,
            ec=ec
        )


def link_protein_enzyme(uniprot_id: str, ec: str):
    """
    (Protein)-[:HAS_EC]->(Enzyme)
    """
    with get_driver().session() as session:
        session.run(
            """
            MATCH (p:Protein {uniprot_id: $uid})
            MATCH (e:Enzyme {ec: $ec})
            MERGE (p)-[:HAS_EC]->(e)
            """,
            uid=uniprot_id,
            ec=ec
        )
