# Security

BlendRender is intended for a trusted operator or a small trusted group. Its controls reduce common
web and Blender-project risks, but Blender is a large native application and this service is not a
strong sandbox for hostile, multi-tenant uploads.

## Trust boundary

Anyone who knows `APP_PASSWORD` can upload projects, start resource-intensive renders, read job
metadata and logs, download completed frames, cancel work, and delete terminal jobs. Give every node
a unique random password and expose it only through HTTPS.

Do not accept untrusted `.blend` files solely because Python auto-execution is disabled. Crafted
files may still exercise Blender parsers, codecs, linked data, render settings, compositor nodes,
and high resource consumption. Isolate the Pod and avoid attaching unrelated credentials or data.

Scene filenames, errors, logs, source projects, and results can contain sensitive project
information. The shared `WORKSPACE_ROOT` should be protected accordingly; every attached Pod can
read its contents.

## Web controls

- Password comparison is constant-time.
- A wrong-password response is delayed by 0.5 seconds. After ten failures, further attempts in the
  rolling minute are rate-limited in that application process.
- Authentication uses a signed HTTP-only, same-site-strict cookie. It is secure by default and
  expires according to `SESSION_TTL_SECONDS`.
- Responses set a restrictive content security policy and deny framing, MIME sniffing, referrer
  data, and camera/microphone/geolocation access.
- Uploaded paths are derived from generated UUIDs. Scene display names and original filenames are
  reduced to a printable base name and are used only as metadata/download naming.
- Uploads are streamed and size-limited. Project ZIPs are limited by both compressed upload and
  extracted regular-file size, then extracted only after rejecting encrypted, special, duplicate,
  absolute, and traversal entries. Archive selections must refer to available frames.

These controls do not provide per-user identity, revocation, audit history, network rate limiting,
or authorization boundaries between jobs.

For storage and deployment precautions, see [Deployment and operations](deployment.md). For scene
requirements and Blender launch behavior, see [Rendering](rendering.md).
