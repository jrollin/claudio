> Reference for: doc-diataxis
> Load when: authoring an Explanation

# Explanation

**Serves:** someone *studying* to deepen *understanding*. Cognition + acquisition.

Explanation is discursive documentation that illuminates a topic: the why, the background, the trade-offs, the connections. Think a thoughtful article read away from the keyboard. Success is the reader coming away with a clearer mental model.

## Voice and stance

- Reflective, discursive prose. Full sentences and paragraphs, not steps or tables.
- It's acceptable — expected — to discuss opinions, history, alternatives, and reasons.
- Written to be read for understanding, possibly when the reader is *not* actively working.

## Structure

- Organized around a **topic or question**, not a task: "Why X works the way it does", "How the Y system is designed".
- Free to make connections: relate this concept to others, compare with alternatives, give historical context.
- No prescribed step format — let the argument shape the flow.

## Must include

- The **why** behind decisions and designs.
- Background, context, and the problem the design solves.
- Trade-offs, alternatives considered, and their consequences.
- Connections between concepts that help the reader build a model.

## Must exclude (these belong elsewhere)

- **Step-by-step instructions** — explanation discusses, it doesn't direct. → how-to / tutorial
- **Exhaustive technical facts** — describe concepts, don't enumerate every parameter. → reference
- **Doing** — the reader is thinking, not executing. If you're telling them to run commands, you've drifted.

## The boundary that's easiest to blur

Explanation and reference both serve *cognition*, so they get conflated. The split is **acquisition vs. application**:

- **Reference** = facts to *apply* while working. Austere, structured, consulted mid-task.
- **Explanation** = understanding to *acquire* while studying. Discursive, opinionated, read reflectively.

"What are the cache settings?" → reference. "Why did we choose write-through caching?" → explanation.

## Title pattern

Topic- or question-framed: "Understanding …", "Why … works this way", "The design of …", "About …", "Background: …".

## Smell test

- Does it deepen understanding rather than enable a task?
- Could the reader get value reading it away from the keyboard?
- Does it discuss the *why* and the trade-offs (not just state facts)?
- Did you avoid turning it into a procedure or a parameter dump?
