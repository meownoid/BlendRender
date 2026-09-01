# Rendering

## Scene input requirements

- Supply a `.blend` file, or a `.zip` that contains exactly one `.blend` plus external resources.
- A ZIP preserves its directory tree. Unpacked images and sounds must use Blender-relative paths
  that resolve within the archive; BlendRender does not rewrite paths or search for missing files.
- FLIP Fluids cache directories must be included in a project ZIP beside their `.blend` file so the
  add-on can resolve the same relative cache path used during baking.
- Pack external images and sounds when uploading a standalone `.blend`.
- Make linked library data local. Project ZIPs intentionally allow only one `.blend`, so separate
  library files are rejected.
- Configure an active camera in the active scene.
- Completing a resumable upload creates an immutable scene; choose a frame or range only when
  creating a later job.

The renderer explicitly detects missing, absolute, and out-of-project unpacked file-backed images,
libraries, and sounds. Production images bundle the public FLIP Fluids Demo v1.8.8 add-on and load
it before the scene opens, so compatible baked FLIP caches can render. Caches baked with the demo
retain its baked watermark; the demo does not include Mixbox color blending. Other external
dependencies, add-ons, fonts, caches, simulations, or system resources may still fail at render
time and should be baked or included where Blender supports it.

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

The optional API overrides are `samples`, Cycles `tile_size` (8–8192), `resolution_x` plus
`resolution_y`, and `resolution_percentage`. The dashboard exposes OptiX, CUDA, and CPU when each
backend is available.

Blender starts with `--background`, `--disable-autoexec`, and `--python-exit-code 1`. When the
bundled FLIP add-on is configured, a fixed trusted bootstrap enables it before the uploaded scene
opens. The application then explicitly runs its own fixed `renderer/blendrender_render.py` script.
User-provided embedded Python is not auto-executed.

## Cancellation, retries, and outputs

Canceling a running job terminates the complete Blender process group. A verified result is published
under its scene with a unique result ID, its producing job and Pod, selected backend/device names,
effective samples, and render duration. Retry reuses published results belonging to that same job
and renders only missing frames. Different jobs may publish separate variants for the same frame.

Each result package contains `frame.png`, `preview.webp`, and `metadata.json`. Preview images are
WebP thumbnails no larger than 720×480. ZIP downloads include PNGs and metadata without PNG
recompression.

For exact request limits and lifecycle operations, see the [API reference](api.md). For the trusted
operator model and web controls, see [Security](security.md).
