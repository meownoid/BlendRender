# Rendering

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

For exact request limits and lifecycle operations, see the [API reference](api.md). For the trusted
operator model and web controls, see [Security](security.md).
