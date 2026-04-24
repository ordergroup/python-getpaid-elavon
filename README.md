# python-getpaid-elavon

[![PyPI version](https://img.shields.io/pypi/v/python-getpaid-elavon.svg)](https://pypi.org/project/python-getpaid-elavon/)
[![Python versions](https://img.shields.io/pypi/pyversions/python-getpaid-elavon.svg)](https://pypi.org/project/python-getpaid-elavon/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Elavon payment processor plugin for the [python-getpaid](https://github.com/django-getpaid/python-getpaid-core) ecosystem.

Provides a fully async HTTP client (`ElavonClient`) and a payment processor (`ElavonProcessor`) implementing the [getpaid-core](https://github.com/django-getpaid/python-getpaid-core) `BaseProcessor` interface. Communicates with Elavon Payment Gateway via their REST API using Basic authentication.

## Features

- **Full Payment Lifecycle**: Supports new, prepared, locked, paid, and failed states.
- **Webhook Verification**: Robust callback signature verification using SHA-512 HMAC.
- **Asynchronous**: Built with `httpx` for non-blocking API communication.
- **Security**: Secure webhook signature validation with configurable signer IDs.
- **Comprehensive API**: Wraps Elavon Payment Gateway REST API endpoints.

## Installation

```bash
pip install python-getpaid-elavon
```

## Configuration

To use the Elavon backend, register it in your `getpaid` configuration and provide the following settings:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `merchant_alias_id` | `str` | — | Elavon merchant alias identifier |
| `secret_key` | `str` | — | Secret key for API authentication |
| `webhook_shared_secret` | `str` | — | Shared secret for webhook signature verification (base64 encoded) |
| `webhook_signer_id` | `str` | — | Signer ID for webhook signature header |
| `sandbox` | `bool` | `True` | Use sandbox (`uat.api.converge.eu.elavonaws.com`) or production (`api.eu.convergepay.com`) |

Example configuration:

```python
GETPAID_BACKENDS = {
    "elavon": {
        "merchant_alias_id": "your_merchant_alias_id",
        "secret_key": "your_secret_key",
        "webhook_shared_secret": "your_base64_encoded_shared_secret",
        "webhook_signer_id": "your_signer_id",
        "sandbox": True,
    }
}
```

### Sandbox Mode

Elavon provides a sandbox environment for testing. Set `sandbox: True` to use the UAT environment.

## Ecosystem

`python-getpaid-elavon` is part of the larger `python-getpaid` ecosystem. Use it with one of our web framework wrappers:

- [django-getpaid](https://github.com/django-getpaid/django-getpaid)
- [litestar-getpaid](https://github.com/django-getpaid/litestar-getpaid)
- [fastapi-getpaid](https://github.com/django-getpaid/fastapi-getpaid)

## Requirements

- Python 3.12+
- `python-getpaid-core >= 3.0.0a2`
- `httpx >= 0.27.0`

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

### Setup

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest -v

# Run linting
uv run ruff check .

# Format code
uv run ruff format .
```

### Available Make Commands

```bash
make test       # Run all tests
make test-cov   # Run tests with coverage
make lint       # Check code with ruff
make format     # Format code with ruff
make fix        # Fix and format code with ruff
```

## License

MIT

## Credits

Created by [Order Group](https://github.com/ordergroup).
