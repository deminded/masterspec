# Spec Delta

## MODIFIED Requirements

### Requirement: Taxed quote
The system SHALL calculate a payable amount by applying 20 percent tax to a
nonnegative decimal subtotal, rounding half up to two decimal places.

#### Scenario: Fractional subtotal
- **WHEN** an internal caller requests a quote for subtotal 10.03
- **THEN** the payable amount is 12.04

#### Scenario: Zero subtotal
- **WHEN** an internal caller requests a quote for subtotal 0
- **THEN** the payable amount is 0

## ADDED Requirements

### Requirement: Tax breakdown
The system SHALL return the original subtotal and tax amount alongside the
payable amount. Tax amount SHALL equal payable amount minus original subtotal.

#### Scenario: Breakdown reconciles
- **WHEN** an internal caller requests a quote for subtotal 10.03
- **THEN** the result contains subtotal 10.03, tax amount 2.01 and payable amount 12.04
