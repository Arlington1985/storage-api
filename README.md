# storage-api

Generic, standalone object-storage presign service backed by Cloudflare R2.
Not tied to Bolt, Wolt, or any specific integration — callers pick their own
full `object_key` (folder path + filename), this service only knows about R2.

- Presigning is a local, offline cryptographic operation (no network call to
  R2), so it's effectively free/instant.
- Reads are served via `302` redirect straight to R2's public URL — no image
  bytes ever flow through this service, keeping Cloud Run cost/egress near-zero
  regardless of read volume.
- Runs independently of `bolt-endpoint` (separate Cloud Run service, separate
  `INTERNAL_API_KEY`), so a credential leak in one can't be used against the
  other.

## Live environments

| Env | URL |
|---|---|
| Dev | https://storage-api-dev-807459983586.europe-west4.run.app |
| Dev (custom domain) | https://storage.api.ramsofter.com *(Cloud Run domain mapping, DNS: CNAME `storage.api` → `ghs.googlehosted.com.`)* |

GCP project: `wolt-456507`, region `europe-west4`, Cloud Run service `storage-api-dev`,
service account `storage-api-dev-sa@wolt-456507.iam.gserviceaccount.com`.

R2: bucket `ramsofter`, account endpoint
`https://e8d3328b06654abaa75b969784762d90.r2.cloudflarestorage.com`, public
read base `https://pub-106b81a8eea342578bf68aa811a8c0ba.r2.dev`.

## API

All endpoints except `/`, `/healthz`, and `GET /<object_key>` require:

```
Authorization: Bearer <INTERNAL_API_KEY>
```

### `POST /presign-upload`

Request:

```json
{"object_key": "wolt/some-restaurant/menu-items/burger-123.jpg", "content_type": "image/jpeg"}
```

- `object_key` — required. Any number of `/`-separated segments of letters,
  digits, `.`, `_`, `-`. No leading `/`, no `..`. This is also the path other
  callers/browsers will use to read the object back.
- `content_type` — optional, defaults to `image/jpeg`.

Response:

```json
{
  "upload_url": "https://<account>.r2.cloudflarestorage.com/ramsofter/wolt/...?X-Amz-...",
  "object_key": "wolt/some-restaurant/menu-items/burger-123.jpg",
  "content_type": "image/jpeg",
  "expires_in": 300,
  "public_url": "https://storage-api-dev-.../wolt/some-restaurant/menu-items/burger-123.jpg"
}
```

`upload_url` is a short-lived (default 300s), single-object, write-only
presigned PUT URL directly to R2. Upload with:

```bash
curl -X PUT "$UPLOAD_URL" -H "Content-Type: image/jpeg" --data-binary @photo.jpg
```

### `GET /<object_key>`

Redirects (`302`) to the real R2 public object. Use `public_url` from the
presign response, or construct it yourself as `{base_url}/{object_key}`.

### `DELETE /<object_key>`

Auth-protected (same `Authorization: Bearer <INTERNAL_API_KEY>` as
`/presign-upload`). Permanently deletes the object from R2.

```bash
curl -X DELETE "$BASE_URL/bolt/pKJYRCxECi/test-aspirin.jpg" \
  -H "Authorization: Bearer $INTERNAL_API_KEY"
```

Response:

```json
{"deleted": true, "object_key": "bolt/pKJYRCxECi/test-aspirin.jpg"}
```

Deleting a key that doesn't exist still returns `200` (S3/R2 delete is
idempotent) — there's no way to distinguish "deleted" from "was already gone".

### `GET /healthz`

Returns `{"status": "ok", "env": "..."}`.

### `GET /`

Plain-text liveness string.

## Full example

```bash
BASE_URL="https://storage-api-dev-807459983586.europe-west4.run.app"

RESP=$(curl -sS -X POST "$BASE_URL/presign-upload" \
  -H "Authorization: Bearer $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"object_key":"bolt/pKJYRCxECi/test-aspirin.jpg","content_type":"image/jpeg"}')

UPLOAD_URL=$(echo "$RESP" | jq -r .upload_url)
PUBLIC_URL=$(echo "$RESP" | jq -r .public_url)

curl -sS -X PUT "$UPLOAD_URL" -H "Content-Type: image/jpeg" --data-binary @photo.jpg

echo "$PUBLIC_URL"   # store this as e.g. Bolt's product image_url

# To remove it later:
curl -X DELETE "$BASE_URL/bolt/pKJYRCxECi/test-aspirin.jpg" \
  -H "Authorization: Bearer $INTERNAL_API_KEY"
```

## Environment variables

Non-secret (`.env`):

| Var | Purpose |
|---|---|
| `APP_ENV` | `development` / `production` |
| `LOCAL_DEV_PORT` | Local Flask dev server port (default 5060) |
| `R2_ENDPOINT_URL` | R2 account endpoint (bucket-LESS) |
| `R2_BUCKET` | R2 bucket name (default `ramsofter`) |
| `R2_PUBLIC_BASE_URL` | R2 public read base URL, no trailing slash |

Secret (via `.envrc` → GCP Secret Manager in dev, `--set-secrets` in Cloud Run):

| Var | Secret Manager ID (dev) |
|---|---|
| `INTERNAL_API_KEY` | `storage-internal-api-key-dev` |
| `R2_ACCESS_KEY_ID` | `r2-access-key-id-dev` |
| `R2_SECRET_ACCESS_KEY` | `r2-secret-access-key-dev` |

## Local development

```bash
direnv allow          # loads secrets via gcloud into the shell
pip install -r requirements.txt
python main.py         # http://localhost:5060
```

## Deploy (dev)

```bash
./deploy-dev.sh
```

Builds the Docker image, pushes to Artifact Registry
(`europe-west4-docker.pkg.dev/wolt-456507/wolt-bolt-integrations/storage-api`),
and deploys to Cloud Run service `storage-api-dev`.
