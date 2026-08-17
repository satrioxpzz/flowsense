# Responsible Disclosure — Jateng CCTV Public Exposure

**Classification:** Responsible disclosure draft (security audit)
**Scope:** Public web page `https://gis.perhubungan.jatengprov.go.id/cctv` and the
downstream kab/kota CCTV servers it references.
**Status of data:** All findings below were obtained from the page's *public* source
(client-side JavaScript) and from unauthenticated HTTP `HEAD`/status probes only.
No video frames were captured and no credentials were replayed.

---

## Summary

Two distinct classes of exposure were confirmed on public infrastructure:

1. **Hardcoded credential in a public client-side script** (Karanganyar ZoneMinder
   stream token embedded in a URL).
2. **Bulk camera metadata exposed without authentication** — 42 CCTV cameras with
   accurate GPS coordinates, names, and stream URLs published directly in the
   public JavaScript of the Jateng portal.

Neither requires any privileged access to observe. Both should be remediated.

---

## Finding 1 — Auth token leaked in URL (Severity: High)

**Affected:** `scctv.karanganyarkab.go.id` (ZoneMinder, Kab. Karanganyar)

The live stream URL embeds an authentication token directly in the query string
and is embedded in client-side JavaScript that ships to every visitor of the
public map page:

```
https://scctv.karanganyarkab.go.id/zm/cgi-bin/nph-zms?scale=100&monitor=48&auth=<TOKEN>&rand=...
```

Observations:
- The token grants direct access to a ZoneMinder monitor (`monitor=48`) via the
  `nph-zms` MJPEG endpoint, which serves `multipart/x-mixed-replace` live frames.
- A token in the URL is exposed in: server/proxy/CDN access logs, browser
  history, and the page's own source.
- The token is static (does not appear to expire) and is identical for all
  public visitors.

**Why it matters:** Anyone can open the public map page, copy the URL, and reach
the raw live stream of a specific camera without any account.

**Recommendation:**
- Remove credentials from URLs. Use `Authorization:` headers or an
  httpOnly, SameSite session cookie.
- If a URL token is required for the player, issue a **signed, short-lived,
  single-use** token (e.g. HMAC with `exp`) rather than a static shared secret.
- Rotate the currently-exposed token immediately and invalidate old values.
- Scope tokens per-session / per-monitor and add rate-limiting.

---

## Finding 2 — Camera inventory & GPS exposed without authentication (Severity: Medium)

**Affected:** `gis.perhubungan.jatengprov.go.id/cctv` and the kab/kota servers it lists.

The portal's `cctvData` JavaScript array publishes **42 cameras**, each with:
- camera name / location,
- administrative region (`wilayah`),
- **accurate GPS latitude/longitude**, and
- the stream/portal URL.

A metadata-only scan of the referenced hosts showed 22/28 responding, including
several that serve a live preview without authentication.

**Why it matters:** Publishing exact GPS of every government CCTV camera, together
with direct stream links, lets anyone enumerate and reach live feeds without any
access control. For most hosts the listed URL is a web portal (HTML) rather than a
raw stream, but the enumeration + coordinates themselves are the exposure.

**Recommendation:**
- Move the camera list behind an authenticated API endpoint (fetch from a
  server-side, access-controlled backend) instead of hardcoding it in public JS.
- Do not publish exact GPS for public, unauthenticated views; if a map is needed,
  show approximate positions or require authentication first.
- Ensure each downstream stream endpoint enforces authentication (note: at least
  one host, `cctv.dishub.magelangkab.go.id`, already returns `401` on `/api/*` —
  this is the correct pattern).

---

## Affected hosts (observed, read-only)

| Host | Observed |
|------|----------|
| `scctv.karanganyarkab.go.id` | Live MJPEG (token-gated, token leaked) |
| `cctv.dishub.magelangkab.go.id` | `/api/*` returns 401 (good) |
| `cctv.pekalongankab.go.id` | Public HTML portal |
| `samudra.jepara.go.id` | Public HTML portal |
| `stream.kuduskab.go.id` | Public HLS (separate, API-keyed feed) |
| `cctv.perhubunganjateng.online` | Aggregator (down at time of scan) |

---

## Suggested remediation priority

1. **Immediate:** rotate the Karanganyar ZoneMinder token; invalidate the leaked
   value.
2. **Short term:** stop embedding tokens in URLs; move to header/cookie auth with
   ephemeral signed tokens.
3. **Short term:** relocate the `cctvData` camera list to an authenticated
   backend endpoint.
4. **Medium term:** remove/obscure exact GPS from public, unauthenticated views;
   add rate-limiting on stream endpoints.

---

## Note on handling

This report was produced for defensive/remediation purposes. The credential in
question is already present in public page source; it is intentionally **not
replayed or stored in full** here. Vendors can retrieve the current value from
their own public page to rotate it. No live video was captured during this audit.

---

*Prepared as part of the FlowSense security review. For internal remediation and
responsible disclosure to the affected Dishub offices.*
