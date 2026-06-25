> Reference for: doc-diataxis
> Load when: authoring a How-to guide

# How-to Guide

**Serves:** a competent user with a *specific goal*, applying skill to *act*. Action + application.

A how-to guide is a recipe: a series of steps that solves one real-world problem. The reader already knows the basics — they came with a task and want to get it done. Success is the goal achieved, efficiently.

## Voice and stance

- Address a capable peer who has a job to do.
- Imperative, action-led: "Set the timeout to…", "Add the following to your config…".
- Assume competence; don't teach fundamentals.

## Structure

1. **Title = the goal** — "How to <achieve a specific outcome>".
2. **Goal statement** — one or two sentences on what this accomplishes and when you'd want it. Prerequisites/assumptions if any.
3. **Ordered steps** — the sequence to reach the goal. Each step is an action.
4. **Result** — how to confirm the goal was reached.
5. **See also** — related how-tos, the relevant reference, or the explanation behind it.

## Must include

- A clear real-world goal in the title.
- The practical sequence of actions to achieve it.
- Real-world messiness where it matters: relevant options, conditional branches ("if you're on Postgres, …"), and the gotchas a working user will actually hit.
- Pointers to recover from common failure modes for *this task*.

## Must exclude (these belong elsewhere)

- **Teaching / first-principles** — the reader isn't a beginner. → tutorial
- **Exhaustive option lists** — mention what's relevant to the goal; link the full list. → reference
- **Conceptual background and rationale** — a sentence is fine; link out for depth. → explanation
- **Unrelated tangents** — one guide solves one problem. Spin off separate guides for separate goals.

## How-to vs. tutorial (the most common confusion)

- A **tutorial** teaches a *beginner* with *no goal* — the steps exist to build skill; the artifact is a vehicle for learning.
- A **how-to** helps a *competent user* with a *real goal* — the steps exist to get the job done.

If the reader already has a problem they're trying to solve, it's a how-to. If they're learning the lay of the land, it's a tutorial. The same sequence of commands can be either, depending on who's reading and why — frame accordingly.

## Title pattern

"How to <goal>": "How to deploy to production", "How to rotate API keys", "How to add a custom domain".

## Smell test

- Does the title name a goal a user would actually search for?
- Could a competent user follow it without being taught basics?
- Did you handle the real-world branches and gotchas (not just the clean path a tutorial would use)?
- Did you resist explaining *why* at length and listing *every* option?
