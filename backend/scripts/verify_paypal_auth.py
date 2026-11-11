import sys

from app.integrations.paypal.client import (
    PayPalAuthenticationError,
    PayPalClient,
)


def main() -> int:
    try:
        token = PayPalClient().get_access_token()
    except PayPalAuthenticationError as error:
        print(f"PayPal authentication failed: {error}", file=sys.stderr)
        return 1

    print(
        "PayPal authentication succeeded. "
        f"Token expires in {token.expires_in} seconds."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
