> Reference for: doc-diataxis
> Load when: authoring a Tutorial

# Tutorial

**Serves:** a learner with *no goal yet*, acquiring skill by *doing*. Action + acquisition.

A tutorial is a lesson. The reader is a beginner being taken by the hand through a meaningful first experience. Success is measured by the learner finishing with a sense of accomplishment and competence — **not** by how much they were told.

## Voice and stance

- You are the teacher; the reader is the student. Take responsibility for what happens.
- First person plural and direct instruction: "We'll build…", "Now run…", "You should see…".
- Speak to *this* learner doing *these* steps now — concrete, not general.

## Structure

1. **What we'll build** — one sentence naming the concrete, tangible outcome.
2. **Before you start** — the minimum prerequisites (a working install, an account). Keep it short; a long prerequisite list signals the tutorial starts too late.
3. **Numbered steps** — small, ordered, each producing a visible result.
4. **What you'll see** — after meaningful steps, state the expected output so the learner can confirm they're on track.
5. **What you learned / next** — a brief recap and a pointer to how-to guides or the next tutorial.

## Must include

- A concrete, achievable end product the learner builds.
- Every command/action needed, in order, with nothing assumed that wasn't established earlier.
- Expected results at checkpoints ("the page now shows…", "the output is…").
- A guaranteed-to-work happy path — the learner must succeed.

## Must exclude (these belong elsewhere)

- **Choices and alternatives** — "you could also use X". A learner can't evaluate options. Pick one path. → reference/explanation
- **Explanation of why** — keep theory to a sentence; link out for the why. → explanation
- **Exhaustive options/flags** — show only what this lesson uses. → reference
- **Edge cases and error recovery** — the happy path only; don't teach troubleshooting here. → how-to
- **Abstract discussion** — stay concrete and in-the-moment.

## The non-negotiable rule

**The tutorial must run end to end as a continuous sequence.** Every step may rely only on state established by earlier steps. A step that assumes a file, variable, or service the tutorial never set up is a bug — fix the sequence. Reason through the whole path as if you were the learner typing each line.

## Title pattern

Outcome-first, beginner-framed: "Build your first …", "Getting started with …", "Your first … in N minutes".

## Smell test

- Did the learner *make* something real? (If they only read, it's not a tutorial.)
- Could a true beginner follow it without getting stuck? (If they need outside knowledge, a step is missing.)
- Did you resist explaining and offering options? (If not, you're drifting into explanation/reference.)
