# FoxPro → storage-api İstifadəçi Təlimatı (Foto Saxlama Xidməti)

Bu sənəd FoxPro proqramının **storage-api** xidmətindən necə istifadə edəcəyini
izah edir: məhsul (və ya istənilən digər) şəklini yükləmək və ona həmişəlik,
ictimai (public) bir link almaq üçün.

`storage-api` — Bolt-dan, bolt-endpoint-dən və hər hansı digər inteqrasiyadan
**asılı olmayan**, müstəqil bir xidmətdir. FoxPro şəkli birbaşa bu xidmətə
göndərir və qaytarılan linki istənilən yerdə (məs. Bolt-un `image_url`
sahəsində) istifadə edə bilər.

---

## ⚙️ Konfiqurasiya dəyərləri

| Dəyər | İzah |
|---|---|
| `BASE_URL` | `https://storage.api.ramsofter.com` |
| `STORAGE_API_KEY` | Məxfi açar — ayrıca, təhlükəsiz şəkildə veriləcək. Koda **yazmayın**, konfiqurasiya faylında saxlayın. |

> ⚠️ `STORAGE_API_KEY` `bolt-endpoint`-in açarından **fərqlidir** — bu, yalnız
> `storage-api`-yə aiddir. Sızma halında biri digərinə təsir etməz.

---

## 0. Əsas prinsip

Proses **2 addımdan** ibarətdir:

1. FoxPro `storage-api`-dən **yükləmə linki (upload_url)** istəyir — bunun üçün
   şəklin haradan/necə saxlanacağını təsvir edən bir **`object_key`** göndərir.
2. FoxPro şəkli **birbaşa** bu linkə (`upload_url`) yükləyir. Şəkil `storage-api`
   serverindən keçmir — birbaşa yaddaşa (Cloudflare R2) gedir, ona görə sürətli
   və ucuzdur.

Cavabda gələn **`public_url`** — şəklin daimi, ictimai linkidir. Bunu istənilən
yerdə (Bolt məhsulunun `image_url` sahəsi, öz bazanız və s.) saxlaya bilərsiniz.

```
FoxPro → (1) POST /presign-upload → upload_url + public_url alır
FoxPro → (2) PUT <upload_url> + şəkil baytları → R2-yə birbaşa yüklənir
FoxPro → public_url-u saxlayır / istifadə edir
```

> Diqqət: yalnız 1 başlıq lazımdır (Bolt-dakı kimi HMAC imza **yoxdur**,
> daha sadədir):
> ```
> Authorization: Bearer <STORAGE_API_KEY>
> ```

---

## 1. Endpoint-lər (OpenAPI-bənzər təsvir)

### 1.1. `POST /presign-upload` — yükləmə linki al

**Sorğu başlıqları:**

```
Authorization: Bearer <STORAGE_API_KEY>
Content-Type: application/json
```

**Sorğu bədəni (JSON):**

| Sahə | Tip | Məcburi? | İzah |
|---|---|---|---|
| `object_key` | string | ✅ Bəli | Şəklin saxlanacağı "yol". Aşağıdakı qaydalara bax (1.2). |
| `content_type` | string | Xeyr | Şəklin MIME tipi. Verilməsə, `image/jpeg` qəbul edilir. |

```json
{
  "object_key": "foxpro/magaza-01/test-aspirin.jpg",
  "content_type": "image/jpeg"
}
```

**Cavab (200 OK, JSON):**

| Sahə | Tip | İzah |
|---|---|---|
| `upload_url` | string | Qısa müddətli (5 dəqiqə), imzalı link. Şəkli birbaşa buraya `PUT` edin. |
| `object_key` | string | Göndərdiyiniz dəyərin təsdiqi. |
| `content_type` | string | Qəbul olunan MIME tipi. |
| `expires_in` | integer | `upload_url`-un neçə saniyəyə etibarsız olacağı (default 300). |
| `public_url` | string | Şəklin **daimi** linki — yükləmə bitdikdən sonra istifadə üçün. |

```json
{
  "upload_url": "https://<hesab>.r2.cloudflarestorage.com/ramsofter/foxpro/...&X-Amz-Signature=...",
  "object_key": "foxpro/magaza-01/test-aspirin.jpg",
  "content_type": "image/jpeg",
  "expires_in": 300,
  "public_url": "https://storage.api.ramsofter.com/foxpro/magaza-01/test-aspirin.jpg"
}
```

**Mümkün xətalar:**

| HTTP kod | Səbəb |
|---|---|
| `401` | `Authorization` başlığı yoxdur və ya `STORAGE_API_KEY` səhvdir. |
| `400` | `object_key` göndərilməyib və ya qadağan olunmuş formatdadır (1.2-yə bax). |

---

### 1.2. `object_key` qaydaları

`object_key` — şəklin "qovluq/fayl adı" kimi düşünülə bilər. Qaydalar:

- Yalnız hərf, rəqəm, `.`, `_`, `-` simvolları və `/` (qovluq ayırıcısı).
- **Əvvəlində `/` ola bilməz** (`foxpro/...` düzgündür, `/foxpro/...` yanlışdır).
- **`..` işlədilə bilməz** (təhlükəsizlik məhdudiyyəti).
- Bir neçə səviyyəli qovluq dəstəklənir: `foxpro/magaza-01/mehsullar/aspirin.jpg`.

**Tövsiyə olunan format:** `foxpro/{magaza_kodu}/{sku}.jpg` — hər SKU üçün
sabit, unikal link təmin edir. Eyni `object_key` ilə yenidən yükləmə edərsənsə,
əvvəlki şəkil sadəcə **əvəz olunur** (link dəyişmir).

---

### 1.3. `GET /{object_key}` — şəkli görüntüləmə

Bu, `public_url`-un özüdür. Brauzerdə açsanız və ya başqa sistemə (məs. Bolt-un
`image_url`-una) versəniz, şəkil birbaşa göstərilir (arxada 302 yönləndirmə
ilə işləyir, sizin üçün şəffafdır).

Nümunə: `https://storage.api.ramsofter.com/foxpro/magaza-01/test-aspirin.jpg`

---

## 2. FoxPro (VFP) tam nümunə

VFP-də daxili JSON parse funksiyası yoxdur. `storage-api` cavabı sadə, sabit
formatlı JSON olduğu üçün, aşağıdakı kiçik köməkçi funksiya (`JsonGetString()`)
kifayət edir — xarici komponent/DLL tələb olunmur.

Binar (şəkil) faylı yükləmək üçün `ADODB.Stream` istifadə olunur — bu, VFP-də
binar HTTP `PUT` göndərmək üçün standart üsuldur.

```foxpro
*!* ==========================================================
*!* storage-api: şəkil yükləmə tam nümunəsi (VFP)
*!* ==========================================================

LOCAL lcBaseUrl, lcApiKey, lcObjectKey, lcContentType, lcFilePath
LOCAL lcRequestBody, lcResponseJson, lcUploadUrl, lcPublicUrl
LOCAL loHttp, lnStatus

lcBaseUrl     = "https://storage.api.ramsofter.com"
lcApiKey      = "YOUR_STORAGE_API_KEY"   && təhlükəsiz konfiqurasiyadan oxuyun
lcObjectKey   = "foxpro/magaza-01/test-aspirin.jpg"
lcContentType = "image/jpeg"
lcFilePath    = "C:\shekiller\test-aspirin.jpg"

*-- 1) Yükləmə linkini al (POST /presign-upload)
lcRequestBody = '{"object_key":"' + lcObjectKey + '","content_type":"' + lcContentType + '"}'

loHttp = CREATEOBJECT("MSXML2.ServerXMLHTTP.6.0")
loHttp.Open("POST", lcBaseUrl + "/presign-upload", .F.)
loHttp.setRequestHeader("Content-Type", "application/json")
loHttp.setRequestHeader("Authorization", "Bearer " + lcApiKey)
loHttp.send(lcRequestBody)

lnStatus = loHttp.status
IF lnStatus # 200
    MESSAGEBOX("Xəta (presign-upload), kod: " + TRANSFORM(lnStatus) + CHR(13) + loHttp.responseText)
    RETURN
ENDIF

lcResponseJson = loHttp.responseText
lcUploadUrl    = JsonGetString(lcResponseJson, "upload_url")
lcPublicUrl    = JsonGetString(lcResponseJson, "public_url")

*-- 2) Şəkli birbaşa upload_url-a yüklə (PUT, binar məzmun)
LOCAL loStream
loStream = CREATEOBJECT("ADODB.Stream")
loStream.Type = 1  && adTypeBinary
loStream.Open()
loStream.LoadFromFile(lcFilePath)

loHttp = CREATEOBJECT("MSXML2.ServerXMLHTTP.6.0")
loHttp.Open("PUT", lcUploadUrl, .F.)
loHttp.setRequestHeader("Content-Type", lcContentType)
loHttp.send(loStream)

lnStatus = loHttp.status
IF lnStatus = 200
    MESSAGEBOX("Uğurlu! Şəklin daimi linki:" + CHR(13) + lcPublicUrl)
    * lcPublicUrl-u öz bazanızda saxlayın / Bolt-un image_url sahəsinə yazın
ELSE
    MESSAGEBOX("Xəta (yükləmə), kod: " + TRANSFORM(lnStatus) + CHR(13) + loHttp.responseText)
ENDIF

*!* ----------------------------------------------------------------
*!* JsonGetString(): sadə, sabit formatlı JSON-dan "key":"value"
*!* dəyərini çıxarır. Yalnız mətn (string) dəyərlər üçündür.
*!* ----------------------------------------------------------------
FUNCTION JsonGetString(tcJson, tcKey)
    LOCAL lcPattern, lnKeyPos, lnColonPos, lnQuoteStart, lnQuoteEnd

    lcPattern = '"' + tcKey + '"'
    lnKeyPos = AT(lcPattern, tcJson)
    IF lnKeyPos = 0
        RETURN ""
    ENDIF

    lnColonPos   = AT(":", SUBSTR(tcJson, lnKeyPos))
    lnQuoteStart = AT('"', SUBSTR(tcJson, lnKeyPos + lnColonPos)) + lnKeyPos + lnColonPos
    lnQuoteEnd   = AT('"', SUBSTR(tcJson, lnQuoteStart + 1)) + lnQuoteStart

    RETURN SUBSTR(tcJson, lnQuoteStart + 1, lnQuoteEnd - lnQuoteStart - 1)
ENDFUNC
```

**İstifadə nümunəsi:**

```foxpro
lcJson = '{"upload_url":"https://example.com/x","object_key":"a/b.jpg","public_url":"https://storage.api.ramsofter.com/a/b.jpg"}'
? JsonGetString(lcJson, "public_url")
* Nəticə: https://storage.api.ramsofter.com/a/b.jpg
```

---

## 3. curl ilə test (istifadəçi əl ilə yoxlamaq istəsə)

```bash
BASE_URL="https://storage.api.ramsofter.com"
API_KEY="YOUR_STORAGE_API_KEY"

# 1) Yükləmə linkini al
RESP=$(curl -sS -X POST "$BASE_URL/presign-upload" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"object_key":"foxpro/magaza-01/test-aspirin.jpg","content_type":"image/jpeg"}')

UPLOAD_URL=$(echo "$RESP" | jq -r .upload_url)
PUBLIC_URL=$(echo "$RESP" | jq -r .public_url)

# 2) Şəkli yüklə
curl -sS -X PUT "$UPLOAD_URL" -H "Content-Type: image/jpeg" --data-binary @test-aspirin.jpg

# 3) Daimi link
echo "$PUBLIC_URL"
```

---

## 4. Qısa xülasə

| Nə etmək | Endpoint | Metod | Açar sahələr |
|---|---|---|---|
| Yükləmə linki al | `/presign-upload` | `POST` | `object_key`, `content_type` |
| Şəkli yüklə | `upload_url` (cavabdan) | `PUT` | binar fayl məzmunu |
| Şəkli göstər / istifadə et | `public_url` (cavabdan) | `GET` | — |

**Əsas qaydalar:**
- Hər sorğuya `Authorization: Bearer <STORAGE_API_KEY>` başlığı əlavə edin
  (yalnız `/presign-upload` üçün lazımdır).
- `object_key` sabit/unikal saxlayın ki, eyni məhsulun şəkli həmişə eyni linkdə qalsın.
- `upload_url` yalnız 5 dəqiqə etibarlıdır — alındıqdan dərhal sonra istifadə edin.
- `public_url`-u öz bazanızda saxlayın — bu, dəyişməyən, daimi linkdir.
