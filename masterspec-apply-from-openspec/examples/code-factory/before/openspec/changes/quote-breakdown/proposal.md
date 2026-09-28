# Proposal

## Why
Internal consumers need cents precision and a visible tax breakdown to explain
the payable amount. The current whole-unit result loses that information.

## What Changes
- Round payable amounts half up to two decimal places, preserving 20% tax.
- Return subtotal and tax amount alongside the payable amount.
- **BREAKING**: the result becomes a breakdown instead of a single amount.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `pricing/quotes`: precision and result content of the internal quotation.

## Impact
The internal quotation contract changes. No persistence, external delivery,
dependency or transport requirement is introduced.
