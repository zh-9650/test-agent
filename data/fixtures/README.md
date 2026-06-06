# Versioned Test Fixtures

These files are reproducible inputs for Layer 1, planning, API, and benchmark
tests. They are source assets, not runtime output.

## Fixture Sets

| Prefix | Purpose |
|---|---|
| `*_aitalk` | Representative internal-style application inputs |
| `*_automation_exercise` | Public e-commerce application inputs |
| `*_purchase` | Small deterministic purchase workflow |
| `prd_minimal.md` | Minimal valid requirements input |
| `prd_adversarial.md` | Ambiguous/low-quality input robustness |

Supported file roles:

- `prd_*.md`: requirements and business rules
- `swagger_*.yaml|json|txt`: API documentation
- `changelog_*.md`: release changes

## Adding A Fixture

1. Use synthetic or public data only.
2. Do not include credentials, private URLs, tokens, cookies, or personal data.
3. Name files consistently by system.
4. Add or update an automated test that consumes the fixture.
5. Add the fixture set to this table.

Generated reports, diagnostic JSON, screenshots, and benchmark outputs belong
under ignored runtime directories and must not be committed.
