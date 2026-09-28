# Quote pricing Specification

## Purpose
Define the internal quotation calculation, without delivery or persistence.

## Requirements

### Requirement: Taxed quote
The system SHALL calculate a payable amount by applying 20 percent tax to a
nonnegative decimal subtotal, rounding half up to the nearest whole unit.

#### Scenario: Fractional subtotal
- **WHEN** an internal caller requests a quote for subtotal 10.03
- **THEN** the payable amount is 12

#### Scenario: Zero subtotal
- **WHEN** an internal caller requests a quote for subtotal 0
- **THEN** the payable amount is 0
