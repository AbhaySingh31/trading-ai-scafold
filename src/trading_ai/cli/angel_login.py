from __future__ import annotations
import argparse, json, re
try:
    import pyotp
except ImportError:
    pyotp = None


def _clean_base32(s: str) -> str:
    """Keep only Base32 alphabet A–Z and 2–7, uppercase. Remove quotes/spaces."""
    return re.sub(r'[^A-Za-z2-7]', '', (s or '')).upper()


def main():
    ap = argparse.ArgumentParser(
        description="Angel One login -> prints JSON with {jwt_token, feed_token} to STDOUT"
    )
    ap.add_argument("--api-key", required=True, help="Angel API key (X-PrivateKey)")
    ap.add_argument("--client-code", required=True, help="Angel client code (login id)")

    # Accept MPIN or password (Angel now uses MPIN; we map --password as an alias)
    ap.add_argument("--mpin", dest="pin", help="Angel MPIN (preferred)")
    ap.add_argument("--password", dest="pin", help="Alias for MPIN (Angel uses MPIN now)")

    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--otp", help="6-digit OTP from the Angel app/SMS")
    grp.add_argument("--totp-secret", help="TOTP secret to auto-generate OTP (requires pyotp)")
    args = ap.parse_args()

    if not args.pin:
        raise SystemExit("Missing --mpin (or --password)")

    # Compute OTP
    otp = args.otp
    if not otp:
        if pyotp is None:
            raise SystemExit("Install pyotp for TOTP: pip install pyotp")
        secret = _clean_base32(args.totp_secret)
        if not secret:
            raise SystemExit("TOTP error: Empty/invalid TOTP secret after sanitization")
        try:
            otp = pyotp.TOTP(secret).now()
        except Exception as e:
            raise SystemExit(f"TOTP error: {e}")

    # Import SmartConnect (support both package names)
    try:
        from SmartApi import SmartConnect  # smartapi-python
    except ImportError:
        try:
            from smartapi import SmartConnect  # alt import name
        except ImportError:
            raise SystemExit("Install Angel SmartAPI: pip install smartapi-python")

    sc = SmartConnect(api_key=args.api_key)

    # Angel backend expects MPIN in 'password' slot for generateSession
    resp = sc.generateSession(args.client_code, args.pin, otp)

    if not resp or not resp.get("status"):
        msg = (resp or {}).get("message", "Unknown error")
        raise SystemExit(f"Login failed: {msg}")

    data = resp.get("data") or {}
    jwt = data.get("jwtToken")
    feed = sc.getfeedToken()

    if not jwt or not feed:
        raise SystemExit(f"Login succeeded but tokens missing: jwt={bool(jwt)} feed={bool(feed)}")

    # Print tokens JSON (no extra text, so redirection to file stays clean)
    print(json.dumps({"jwt_token": jwt, "feed_token": feed}, indent=2))


if __name__ == "__main__":
    main()
