# Security and rendering

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

Job filenames, errors, and logs can contain sensitive project information. `DATA_ROOT` contains the
uploaded source projects as well as output and should be protected accordingly.

## Web controls

- Password comparison is constant-time.
- A wrong-password response is delayed by 0.5 seconds. After ten failures, further attempts in the
  rolling minute are rate-limited in that application process.
- Authentication uses a signed HTTP-only, same-site-strict cookie. It is secure by default and
  expires according to `SESSION_TTL_SECONDS`.
- Mutating browser requests with an `Origin` different from the current scheme and host are
  rejected.
- Responses set a restrictive content security policy and deny framing, MIME sniffing, referrer
  data, and camera/microphone/geolocation access.
- Uploaded paths are derived from generated UUIDs. Original filenames are reduced to their base
  name and are used only as metadata/download naming.
- Uploads are streamed and size-limited; archive selections must refer to available frames.

These controls do not provide per-user identity, revocation, audit history, network rate limiting,
or authorization boundaries between jobs.

## Scene input requirements

- Supply exactly one `.blend` file.
- Pack external images and sounds into the project.
- Make linked library data local so the upload is self-contained; references to separate library
  files cause the job to fail.
- Configure an active camera in the active scene.
- Verify the scene at the requested frame or frame range before upload.

The renderer explicitly detects missing unpacked file-backed images, libraries, and sounds. Other
external dependencies, add-ons, fonts, caches, simulations, or system resources may still fail at
render time and should be baked or packed where Blender supports it.

## Settings preserved and overridden

The uploaded active scene supplies camera choice and, unless optional request overrides are used,
resolution, resolution percentage, and Cycles sample count. Denoising, compositor setup, and color
management remain scene-controlled.

For every job, BlendRender overrides:

- render engine to Cycles;
- compute device to the requested CPU, CUDA, or OptiX backend;
- requested frame sequence;
- render output path;
- image format to PNG; and
- file-extension output behavior.

The optional API overrides are `samples`, `resolution_x` plus `resolution_y`, and
`resolution_percentage`. The dashboard exposes OptiX, CUDA, and CPU when each backend is available.

Blender starts with `--background`, `--disable-autoexec`, and `--python-exit-code 1`. The application
then explicitly runs its own fixed `renderer/blendrender_render.py` script. User-provided embedded
Python is not auto-executed.

## Cancellation, retries, and outputs

Canceling a running job terminates the complete Blender process group. Frames already written as
valid PNG files are retained. Retry verifies each expected PNG with Pillow and renders only missing
or invalid frames; it does not guarantee that retained frames came from identical scene settings if
the on-disk job directory has been altered outside the application.

Output names are deterministic (`frame_000001.png`). Preview images are WebP thumbnails no larger
than 720×480. ZIP downloads use no compression because PNG files are already compressed.

For exact request limits and lifecycle operations, see the [API reference](api.md). For storage and
health considerations, see [Deployment and operations](deployment.md).
