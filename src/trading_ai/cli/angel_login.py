
from __future__ import annotations
import argparse, json
try:
    import pyotp
except ImportError:
    pyotp = None

def main():
    ap = argparse.ArgumentParser(description="Angel One login -> prints jwt_token and feed_token")
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--client-code", required=True)
    ap.add_argument("--password", required=True)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--otp", help="Manual 2FA OTP (from app/SMS)")
    grp.add_argument("--totp-secret", help="TOTP secret to auto-generate OTP (requires pyotp)")
    args = ap.parse_args()

    if args.totp_secret and pyotp is None:
        raise SystemExit("Install pyotp for TOTP: pip install pyotp")

    otp = args.otp
    if not otp:
        otp = pyotp.TOTP(args.totp_secret).now()

    try:
        from SmartApi import SmartConnect
    except ImportError:
        raise SystemExit("Install Angel SmartAPI: pip install smartapi-python")

    sc = SmartConnect(api_key=args.api_key)
    data = sc.generateSession(args.client_code, args.password, otp)
    if not data or "data" not in data:
        raise SystemExit(f"Login failed: {data}")
    jwt = data["data"]["jwtToken"]
    feed = sc.getfeedToken()

    print(json.dumps({"jwt_token": jwt, "feed_token": feed}, indent=2))

if __name__ == "__main__":
    main()
