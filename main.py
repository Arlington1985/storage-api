# main.py - Generic object storage presign service for storage.api.ramsofter.com
#
# Fully generic: callers (bolt-endpoint, wolt-endpoint, or anything else) pick
# their own full object_key (e.g. "bolt/pKJYRCxECi/test-aspirin.jpg"). This
# service knows nothing about Bolt/Wolt/products - just R2 objects. Two jobs:
#   1. POST /presign-upload  - caller gets a short-lived, signed R2 PUT URL for
#      exactly one object_key. Credentials never leave this server.
#   2. GET /<path:object_key> - redirects to the real R2 public object. This is
#      a 302, not a proxy: no bytes ever pass through this service, so Cloud
#      Run cost/egress stays near-zero no matter how often it's read.
import os
import re
from functools import wraps

from flask import Flask, request, jsonify, abort, redirect
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv, find_dotenv

try:
    import boto3
    from botocore.config import Config as BotoConfig
except ImportError:  # pragma: no cover
    boto3 = None
    BotoConfig = None

load_dotenv(find_dotenv('.env', raise_error_if_not_found=False, usecwd=True), override=True)

app = Flask(__name__)
# Cloud Run terminates TLS at its proxy and forwards plain HTTP, setting
# X-Forwarded-Proto/-Host. Without this, request.host_url/scheme would report
# http:// even though the public-facing URL is https://.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

APP_ENV = os.getenv('APP_ENV', 'development')

# Auth for the presign endpoint (FoxPro -> this service). Reuse the same
# bearer-token style as bolt-endpoint for consistency, but this is a separate
# key/secret - a leak here can't be used against the Bolt API and vice versa.
INTERNAL_API_KEY = os.getenv('INTERNAL_API_KEY')

# Cloudflare R2. R2_ENDPOINT_URL is the bucket-LESS account endpoint - the
# bucket name goes in R2_BUCKET, never in the endpoint URL.
R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL')
R2_BUCKET = os.getenv('R2_BUCKET', 'ramsofter')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_PRESIGN_EXPIRES_SECONDS = int(os.getenv('R2_PRESIGN_EXPIRES_SECONDS', 300))
# Public read base (R2's public dev URL / bucket domain) that this service
# redirects reads to. NOT the same as our own public-facing storage.api.ramsofter.com.
R2_PUBLIC_BASE_URL = os.getenv('R2_PUBLIC_BASE_URL')

required_vars = ["INTERNAL_API_KEY", "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID",
                  "R2_SECRET_ACCESS_KEY", "R2_PUBLIC_BASE_URL"]
missing_vars = [var for var in required_vars if not globals().get(var)]
if missing_vars:
    print(f"FATAL: Missing required environment variables: {', '.join(missing_vars)}")
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

r2_client = None
if boto3:
    r2_client = boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name='auto',
        config=BotoConfig(signature_version='s3v4'),
    )
    print(f"R2 client initialized for bucket '{R2_BUCKET}'.")
else:
    print("FATAL: boto3 is not installed; this service cannot function.")
    raise ImportError("boto3 is required")


# Allowed object_key format: one or more path segments of safe characters,
# separated by '/'. No leading '/', no '..', no empty segments. This is the
# only guardrail - callers are fully responsible for their own key layout
# (e.g. bolt-endpoint sends "bolt/{provider_id}/{product_id}.jpg").
_OBJECT_KEY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$')


def validate_object_key(object_key: str) -> str:
    if not object_key or '..' in object_key or not _OBJECT_KEY_RE.match(object_key):
        raise ValueError(
            "Invalid object_key. Use one or more '/'-separated segments of "
            "letters, digits, '.', '_', '-' (no leading '/', no '..')."
        )
    return object_key


def generate_upload_url(object_key: str, content_type: str = 'image/jpeg') -> str:
    """Returns a presigned PUT URL for exactly the given object_key."""
    return r2_client.generate_presigned_url(
        'put_object',
        Params={'Bucket': R2_BUCKET, 'Key': object_key, 'ContentType': content_type},
        ExpiresIn=R2_PRESIGN_EXPIRES_SECONDS,
    )


def require_internal_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            abort(401, "Missing or invalid Authorization header")
        provided_key = auth_header.split('Bearer ')[1]
        import hmac
        if not (INTERNAL_API_KEY and hmac.compare_digest(provided_key, INTERNAL_API_KEY)):
            abort(403, "Invalid API Key")
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    return f"Photo Storage API ({APP_ENV}) is running."


@app.route('/healthz')
def healthz():
    return jsonify({"status": "ok", "env": APP_ENV}), 200


@app.route('/presign-upload', methods=['POST'])
@require_internal_api_key
def api_presign_upload():
    data = request.get_json(silent=True) or {}
    object_key = data.get('object_key')
    content_type = data.get('content_type') or 'image/jpeg'
    if not object_key:
        abort(400, "Missing 'object_key'")
    try:
        object_key = validate_object_key(object_key)
    except ValueError as e:
        abort(400, str(e))
    upload_url = generate_upload_url(object_key, content_type)

    request_host = request.host_url.rstrip('/')
    public_url = f"{request_host}/{object_key}"
    return jsonify({
        "upload_url": upload_url,
        "object_key": object_key,
        "content_type": content_type,
        "expires_in": R2_PRESIGN_EXPIRES_SECONDS,
        "public_url": public_url,
    }), 200


@app.route('/<path:object_key>')
def serve_object(object_key):
    """Redirects to the real R2 public object. No bytes flow through this
    service - callers/browsers follow the 302 straight to R2's own CDN."""
    try:
        object_key = validate_object_key(object_key)
    except ValueError as e:
        abort(400, str(e))
    target = f"{R2_PUBLIC_BASE_URL.rstrip('/')}/{object_key}"
    return redirect(target, code=302)


if __name__ == '__main__':
    port = int(os.getenv('LOCAL_DEV_PORT', 5060))
    print(f"Starting local server on http://0.0.0.0:{port} with debug=True")
    app.run(host='0.0.0.0', port=port, debug=(APP_ENV == 'development'))
