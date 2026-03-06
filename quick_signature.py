import base64
import hashlib
import json


# ============================================================================
# PASTE YOUR VALUES HERE
# ============================================================================

WEBHOOK_SHARED_SECRET = ""
WEBHOOK_SIGNER_ID = ""

USE_EXACT_JSON = True

JSON_MESSAGE = """{"href": "https://uat.api.converge.eu.elavonaws.com/notifications/gm8p2km34rq3c9vkmjwjvqjrfkf2","id": "gm8p2km34rq3c9vkmjwjvqjrfkf2","merchant": "https://uat.api.converge.eu.elavonaws.com/merchants/q8cjcb6cx6b932c77c6y9tmmpx3k","createdAt": "2026-03-03T11:00:01.521Z","eventType": "expired","resourceType": "paymentSession","resource": "https://uat.api.converge.eu.elavonaws.com/payment-sessions/2w3c6gtww8rj8qq38fb3xcfkt9gm","customReference": "3cba32ea-5efa-404e-b62b-ee1ee6aeada8"}"""  # noqa: E501


# ============================================================================
# SCRIPT - NO NEED TO MODIFY BELOW
# ============================================================================


def generate_signature():
    # Compact JSON (remove whitespace)
    if USE_EXACT_JSON:
        body_str = JSON_MESSAGE.strip()  # Keep spaces, remove only outer whitespace
    else:
        json_obj = json.loads(JSON_MESSAGE)
        body_str = json.dumps(json_obj, separators=(",", ":"), ensure_ascii=False)
    # Decode shared secret
    shared_secret_bytes = base64.b64decode(WEBHOOK_SHARED_SECRET)

    # Convert JSON to bytes
    body_bytes = body_str.encode("utf-8")

    # Concatenate: shared_secret + body
    final_bytes = shared_secret_bytes + body_bytes

    # SHA-512 hash
    hash_result = hashlib.sha512(final_bytes).digest()

    # Base64 encode
    signature = base64.b64encode(hash_result).decode("utf-8")

    # Header name
    header_name = f"Signature-{WEBHOOK_SIGNER_ID}"

    print("=" * 80)
    print("WEBHOOK SIGNATURE GENERATED")
    print("=" * 80)
    print(f"\n📋 Header Name:\n{header_name}")
    print(f"\n🔐 Signature Value:\n{signature}")
    print(f"\n📄 Compact JSON Body:\n{body_str.encode('utf-8')}")
    print("\n" + "=" * 80)
    print("POSTMAN SETUP")
    print("=" * 80)
    print("1. Method: POST")
    print(f"2. Headers → Add: {header_name}")
    print(f"3. Value: {signature}")
    print("4. Body → raw → JSON → paste compact JSON above")
    print("=" * 80)


if __name__ == "__main__":
    generate_signature()
