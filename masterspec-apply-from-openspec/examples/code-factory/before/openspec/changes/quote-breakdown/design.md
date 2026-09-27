# Design

## Context
`src/pricing.py` currently returns one Decimal rounded to whole units.
See proposal.md for motivation. The return contract changes incompatibly.

## Goals / Non-Goals
**Goals:** retain decimal arithmetic and make the new return shape explicit.
**Non-Goals:** persistence, a transport API, external delivery or new dependencies.

## Decisions
Use a named result with subtotal, tax and payable values. A scalar cannot carry
the breakdown; positional values make their meaning less explicit.

## Risks / Trade-offs
Existing scalar consumers require migration. The example has no external
consumers, so it cannot prove compatibility for a larger application.

## Migration Plan
Change the return contract and its callers together; revert that change together
if acceptance cases fail. This document is planning only.
