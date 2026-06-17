# SpotOn Unofficial API

Unofficial Python integrations for SpotOn.

## Integrations

- `spoton_get_time_clock_entries.py` - `get_time_clock_entries`.
- `spoton_get_labor_report.py` - `get_labor_report`.
- `spoton_get_orders.py` - `get_orders`.
- `spoton_get_labor_breakdown.py` - `get_labor_breakdown`.

## Usage

Each file exposes a `run(input, context)` entrypoint. The runtime is expected to provide:

- `input`: integration-specific request fields.
- `context["headers"]`: authenticated request headers when required.
- `context["base_url"]`: the platform base URL when overriding the default.

Install dependencies:

```bash
pip install -r requirements.txt
```

## Info

This unofficial API is built by [Integuru](https://integuru.com).

For custom requests or hosted authentication, contact richard@integuru.com or [schedule time with us](https://calendly.com/d/cqb8-d9x-nbf/integuru).

See the [complete list of APIs by Integuru](https://github.com/Integuru-AI/APIs-by-Integuru).
