---
name: de-aigc-writing
description: Use when the user wants to reduce obvious AIGC writing traces, humanize prose, or rewrite text so it sounds less formulaic and more natural while preserving meaning. Trigger on requests to reduce AI tone, remove machine-written style, make prose sound more natural, or revise Chinese or English text that feels too polished, repetitive, generic, or machine-generated.
---

# De-AIGC Writing

## Goal

Rewrite text so it reads like strong human writing rather than template-heavy AI output. Preserve facts, intent, terminology, and usable structure unless the user explicitly asks for deeper restructuring.

## Workflow

1. Diagnose the source text before rewriting.
   - Identify whether the main problem is emptiness, repetition, over-structure, exaggerated smoothness, or generic phrasing.
   - Identify the required register: academic, business, public-facing, personal statement, social post, or general prose.
2. Preserve non-negotiable content.
   - Keep factual claims, citations, numbers, names, and domain terms unless the user asks to change them.
   - Keep the original stance and intended audience.
   - Do not invent anecdotes, data, quotations, or personal experience.
3. Rewrite for natural variation.
   - Vary sentence length and rhythm.
   - Replace abstract filler with concrete wording already supported by the source.
   - Remove robotic transitions unless they are genuinely useful.
   - Break overly symmetrical paragraph structure when it improves flow.
4. Tighten weak sections.
   - Cut duplicated claims.
   - Replace stacked adjectives with one precise description.
   - Convert empty summaries into sharper assertions when the source supports them.
5. Run a final pass against the checklist in `references/checklist.md`.

## Common AIGC Markers

- Repeated scaffold phrases such as "first/second/finally", "it is worth noting that", "overall", "in today's world", or other stock transitions.
- Paragraphs that all have the same cadence, density, and sentence length.
- Abstract noun piles with low information density.
- Overuse of safe verbs such as "optimize", "enhance", "leverage", "promote", "deliver", or other vague operation words.
- Excessive balance and completeness: every point sounds equally polished, equally hedged, and equally generic.
- Conclusions that restate the obvious instead of landing on a specific implication.

## Rewrite Principles

Use these defaults unless the user asks otherwise:

- Prefer concrete nouns and direct verbs over inflated abstractions.
- Keep some natural asymmetry across sentences and paragraphs.
- Let one or two points carry more weight; do not force false balance.
- Prefer specific connective logic over stock transitions.
- Keep tone controlled. Do not swing from flat AI-sounding prose into melodrama, slang, or fake intimacy unless the user asks for that style.
- Preserve the user's original level of sophistication. Do not dumb content down just to sound human.

## Mode Selection

Pick the lightest rewrite that solves the problem:

- Light pass: Remove visible stock phrases, vary cadence, trim filler.
- Standard pass: Reshape paragraphs, sharpen claims, reduce symmetry, keep the same structure.
- Deep pass: Rebuild sequencing and emphasis, merge or split paragraphs, rewrite transitions aggressively.

If the user does not specify intensity, use the standard pass.

## Writing Constraints

- Do not promise the text will bypass detectors.
- Do not fabricate human-only signals such as field experience, emotions, interviews, or lived events.
- Do not change technical conclusions just to sound more human.
- For academic or formal writing, keep citation anchors and terminology stable.
- When a sentence is already crisp and credible, leave it alone.

## Output Style

Default to returning only the rewritten text. Add a short explanation of what changed only when the user asks for commentary, comparison, or a checklist.

If the user provides multiple paragraphs, preserve paragraph breaks unless restructuring materially improves readability.

## Prompt Patterns

- "Reduce the AI tone in this passage without changing the argument."
- "Make this paragraph sound more natural but keep the academic register."
- "Rewrite this copy so it feels less templated and more editor-driven."
- "Humanize this paragraph without changing the technical meaning."

## Reference

Use `references/checklist.md` for a compact pre-delivery scan of high-risk AI-sounding patterns.
