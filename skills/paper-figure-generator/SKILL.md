---
name: paper-figure-generator
description: Use when the user wants to generate a scientific figure, graphical abstract, mechanism diagram, workflow diagram, cover-style illustration, or paper companion image from the content of a research paper, abstract, notes, or results section. Trigger on requests to make a figure from a paper, convert a manuscript section into a visual, draft a scientific illustration prompt, or design a publication-ready concept without inventing unsupported data or claims.
---

# Paper Figure Generator

## Goal

Turn paper content into a faithful figure plan, layout, and image-generation prompt. Preserve the paper's claims, entities, and uncertainty, and choose a figure type that matches the available evidence instead of forcing every request into a glossy infographic.

## Input Sources

Accept any of the following as source material:

- Full paper text
- Abstract plus methods or results excerpt
- Bullet notes from a manuscript
- Figure legend draft
- Section summaries from a PDF reading workflow
- A user brief such as "make a graphical abstract for this study"

If the source is incomplete, prefer a concept figure over a precise quantitative figure.

## Workflow

1. Extract the scientific core.
   - Identify the study question, system, organism, modality, key variables, and main finding.
   - List named entities that must stay accurate: genes, proteins, cell types, pathways, assays, drugs, cohorts, tissues, species, instruments.
2. Choose the right figure type using `references/figure-types.md`.
   - Use mechanism or concept figures when the paper argues causality or pathway logic.
   - Use workflow diagrams for methods or pipelines.
   - Use result-summary figures only when the paper contains enough stable findings to summarize visually.
   - Use quantitative charts only when the paper provides actual numbers or unambiguous directional comparisons.
3. Define the visual grammar.
   - Decide the number of panels, reading order, labels, and focal element.
   - Decide whether the image should be publication-like, graphical-abstract style, educational, or cover-art style.
   - Keep the aesthetic subordinate to scientific accuracy.
4. Produce the output in layers.
   - A concise figure concept
   - A panel-by-panel layout
   - A generation prompt or drawing brief
   - Optional caption or legend if the user asks
5. Run the final check against `references/quality-checklist.md`.

## Figure Rules

- Do not invent effect sizes, p-values, sample counts, or trends that are not in the source.
- Do not draw a bar chart, volcano plot, heatmap, Kaplan-Meier curve, or other quantitative panel unless the source supports it.
- If the evidence is qualitative or partial, state that clearly and switch to a conceptual or schematic figure.
- Keep causal arrows, inhibition marks, and activation marks faithful to what the paper claims.
- If the paper is uncertain, controversial, or correlative, reflect that uncertainty in the figure language.
- Avoid decorative biomedical cliches when they do not serve the result.

## Output Format

Default to this structure unless the user asks for something else:

1. Figure type
2. Visual rationale
3. Panel plan
4. Image prompt or illustration brief
5. Optional caption

Keep the response concise and concrete. Do not spend most of the answer explaining your reasoning.

## Prompting Strategy

- For image-generation tools, write prompts that specify composition, entities, relationships, annotation style, panel count, and color logic.
- Prefer "clean scientific schematic", "graphical abstract", "journal figure style", or similarly specific styles over vague words such as "beautiful" or "professional".
- If the user wants a raster image, it is appropriate to use an image-generation workflow after the scientific layout has been nailed down.
- If the user wants editable diagrams, prefer a structured brief that can be recreated in SVG, Canva, PowerPoint, or vector tools.

## Common Requests

- "Turn this abstract into a graphical abstract."
- "Make a mechanism diagram from this results section."
- "Generate a cover-style figure for this cancer paper."
- "Convert this methods pipeline into a visual workflow."
- "Read this manuscript summary and draft a three-panel companion figure."

## Constraints

- Do not fabricate microscopy views, anatomical detail, molecular structures, or experimental outcomes that are not grounded in the source.
- Do not turn a narrow result into a universal claim.
- Do not silently simplify the biology if that changes the meaning.
- When the source is too thin for a faithful figure, say what is missing and provide the best safe fallback concept.

## References

Read `references/figure-types.md` when choosing between graphical abstract, mechanism figure, workflow, concept art, and quantitative summary. Read `references/quality-checklist.md` before finalizing any scientific image brief.
