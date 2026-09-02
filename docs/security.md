# Security

BlendRender is designed for a trusted operator or small trusted team. It is not a secure sandbox
for hostile uploads or a service with separate user accounts.

## Access and isolation

Anyone with `APP_PASSWORD` can read shared scenes and results, upload projects, start renders,
and delete data. Job cancellation, retry, and deletion must go through the owning Pod.

Use a long, random password shared only with trusted operators. Pods sharing a workspace should
use the same password. Expose the service through HTTPS with `COOKIE_SECURE=true`.

Blender's embedded Python auto-execution is disabled, but crafted files can still exercise native
parsers, codecs, and resource-intensive settings. Isolate the Pod from unrelated data and
credentials. Every Pod attached to the network volume can read its contents, including project
files and logs.

The bundled FLIP Fluids add-on is trusted image code loaded before the scene opens. Uploads cannot
install their own add-ons through this mechanism.

## Built-in controls

- Signed, HTTP-only, same-site-strict session cookies, secure by default and valid for seven days
  unless `SESSION_TTL_SECONDS` is changed.
- Constant-time password comparison, delayed failures, and a per-process login limit after ten
  failed attempts in a rolling minute.
- Cross-origin mutation checks and restrictive response headers for scripts, framing, referrers,
  MIME handling, and browser permissions.
- UUID-based storage paths and sanitized display names.
- Size-limited, ordered upload chunks with 24-hour expiry for inactive staging data.
- ZIP validation that rejects unsafe paths, duplicate entries, encryption, and special files;
  both uploaded and extracted sizes are limited, with at most 100,000 entries.

These controls do not provide per-user permissions, individual session revocation, audit history,
or network-level rate limiting. For deployment settings, see [Deployment](deployment.md).
