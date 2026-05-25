# AGENTS.md

## Scope

This file defines the project-specific collaboration rules for Codex agents working in `C:\Users\70713\Desktop\BioKG-1`.

It applies to the whole repository unless a deeper `AGENTS.md` overrides part of it.

## Project Summary

BioKG is a biomedical knowledge graph project built around:

- KEGG structured pathway and enzyme ingestion
- PubMed incremental literature retrieval and entity linking
- Neo4j graph storage and querying
- Graph-based RAG over local LLMs through Ollama
- Streamlit-based interactive exploration UI

The repository also contains thesis assets under `thesis_materials/`; those files support documentation and figures, not the primary runtime path.

## Source Of Truth

When making implementation decisions, treat the following as the primary operational entry points:

- `BioKG/app.py`: Streamlit UI entry point
- `BioKG/main.py`: CLI entry point
- `BioKG/pipeline/build_kg.py`: initial KEGG graph build
- `BioKG/pipeline/update_pipeline.py`: PubMed incremental update pipeline
- `BioKG/config/config.py`: default project configuration

## Repository Map

- `BioKG/config/`: configuration constants
- `BioKG/data/`: local data files and dictionaries
- `BioKG/kegg/`: KEGG API integration and parsing
- `BioKG/pubmed/`: PubMed retrieval, parsing, NER, linking, and write logic
- `BioKG/neo4j_utils/`: Neo4j connection and write helpers
- `BioKG/pipeline/`: orchestration scripts for graph build and updates
- `BioKG/RAG/`: knowledge retrieval and answer generation
- `BioKG/tests/`: lightweight connection and writer checks
- `thesis_materials/`: thesis drafts, rendering scripts, and figure assets
- `skills/`: local skill definitions; not core application runtime

## Codex Working Agreement

Codex should optimize for small, verifiable changes that preserve existing module boundaries.

### Do

- Read the relevant execution path before editing.
- Prefer fixing the problem in the owning module instead of patching around it in `BioKG/app.py`.
- Keep data retrieval, parsing, graph writing, and answer generation separated.
- Preserve backward compatibility for existing Neo4j labels, property names, and relationship types unless the task explicitly requires a schema migration.
- Use environment-variable-first patterns for secrets or local machine settings.
- Treat `BioKG/app.py` import path handling as intentional; it supports running from the repository root.

### Do Not

- Do not move business logic into the UI layer unless the task is explicitly UI-only.
- Do not introduce new credentials or machine-specific secrets into committed files.
- Do not casually rewrite schema names such as node labels, property keys, or relation names used by Neo4j queries.
- Do not modify thesis files just because they mention similar concepts; change them only when the task is explicitly about thesis artifacts.
- Do not assume a full dependency lockfile exists; verify before adding new packages or commands that depend on them.

## Environment Assumptions

This project appears to rely on the following external services or tools:

- Neo4j at `neo4j://127.0.0.1:7687`
- local Ollama models for RAG generation
- SciSpacy model(s) for biomedical NER
- PubMed E-utilities access
- KEGG REST access

`BioKG/config/config.py` currently contains development defaults, including a placeholder PubMed email and local Neo4j credentials. Prefer preserving compatibility while improving configuration hygiene.

## Preferred Development Flow

For any non-trivial task, follow this order:

1. Identify the affected path:
   - KEGG ingestion
   - PubMed retrieval/parsing/linking
   - Neo4j write/query logic
   - RAG retrieval/generation
   - Streamlit UI behavior
2. Read the immediate entry point and its directly called module(s).
3. Make the smallest coherent code change in the owning module.
4. Run the narrowest useful verification.
5. Report what changed, what was verified, and any remaining environmental dependency.

## Validation Expectations

Run targeted checks whenever possible instead of relying on inspection alone.

Typical commands from repository root:

```powershell
streamlit run BioKG/app.py
python BioKG\main.py --stats
python BioKG\main.py --update
python BioKG\main.py --ask "LDHA" --model "deepseek-r1:7b"
pytest BioKG\tests -q
```

Validation guidance:

- Neo4j connection or writer change: run the connection/writer checks first.
- Pipeline change: prefer a small-scope run before any broader update.
- RAG change: verify both context construction and answer generation path.
- UI change: launch Streamlit and confirm the affected interaction path.

If a check cannot run because of missing services, missing models, or missing dependencies, say so explicitly.

## Schema Safety

This repository is graph-schema-sensitive. Before editing Cypher or write paths:

- confirm the exact label names already used in queries
- confirm the exact property keys already used by readers and writers
- preserve compatibility for relation types such as `MENTIONS` and `MENTIONS_EC`
- avoid "cleanup refactors" that rename graph fields without a migration plan

If a task requires schema evolution, document:

- old shape
- new shape
- compatibility impact
- required backfill or migration steps

## Files That Need Extra Care

- `BioKG/app.py`
  - Contains path bootstrapping and mixed UI/query responsibilities.
- `BioKG/pipeline/update_pipeline.py`
  - Drives incremental PubMed updates and dynamic synonym loading from Neo4j.
- `BioKG/pubmed/*`
  - Changes here can affect NER quality, linking precision, and graph consistency.
- `BioKG/RAG/rag_engine.py`
  - Changes here can alter both retrieval quality and generation behavior.
- `BioKG/config/config.py`
  - Keep defaults safe; avoid hardcoding sensitive values.

## Non-Core Areas

Unless the task explicitly targets them, treat these as out of scope:

- `thesis_materials/`
- generated output files under `output/`
- temporary artifacts under `tmp/`

Do not "synchronize" thesis wording with runtime code unless requested.

## Change Style

- Prefer narrow diffs over broad formatting-only rewrites.
- Add comments only where the logic is not self-evident.
- Preserve existing naming unless a rename materially improves correctness.
- Keep new code ASCII unless the file already relies on non-ASCII content for user-facing text.

## Completion Checklist

Before finishing, Codex should confirm:

- the change is placed in the correct module
- no unrelated files were modified without reason
- the relevant path was verified, or the verification blocker is stated
- any external dependency requirement is called out clearly

## Notes For Future Agents

Start with `BioKG/app.py`, `BioKG/main.py`, and `BioKG/pipeline/update_pipeline.py` when you need to orient quickly.

If the issue is ambiguous, first classify it as one of:

- ingestion
- parsing/linking
- graph persistence
- retrieval/generation
- UI/query presentation

Do not guess across these boundaries when the code can tell you which layer owns the behavior.

<!-- ARIS:BEGIN -->
## ARIS Skill Scope
For ARIS workflows in this project, use only the project-local ARIS skills under `.agents/skills/aris`.
Do not use global skills or non-ARIS project skills unless the user explicitly asks to mix them.
<!-- ARIS:END -->
