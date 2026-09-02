# Rendering

## Prepare a scene

- Upload a `.blend` with images packed, or a ZIP containing exactly one `.blend` and its external
  image resources.
- Use Blender-relative paths for unpacked resources. ZIPs preserve folders; BlendRender does not
  rewrite paths or locate missing files.
- Make linked library data local: separate `.blend` libraries are not allowed in project ZIPs.
- Set an active camera in the scene you want to render.
- Bake simulations and include their caches and other dependencies where supported.

Uploads create reusable scenes without starting a render. Select the scene and choose **New render**
to create a job. Upload a new scene when the source changes; see the
[S3 guide](s3-guide.md#replace-scene-source-files) for offline source replacement.

The renderer checks unpacked images and libraries for missing or out-of-project paths. Other
dependencies, including fonts, add-ons, and simulation caches, may still fail at render time.
Third-party Blender add-ons are not supported on render Pods; the production image provides only
the bundled FLIP Fluids Demo add-on described below.

## FLIP Fluids

The production image bundles FLIP Fluids Demo v1.8.8. Include baked caches in a project ZIP alongside
the `.blend`, preserving the relative cache path used during baking. The add-on loads before the
scene opens. Demo-baked caches retain their watermark; Mixbox color blending is not included.

## Render settings

The active scene supplies the camera, denoising, compositor, and color management. Samples,
resolution, resolution percentage, and Cycles tile size use scene settings unless overridden.

Every job uses Cycles, the selected backend and frame sequence, and PNG image output. Image output
is currently the only supported result type. The dashboard supports OptiX, CUDA, and CPU when
available on the Pod. Samples, tile size, and resolution can be adjusted per job; see
[API limits](api.md#jobs).

Blender runs in background mode with `--disable-autoexec` and `--python-exit-code 1`. Only the
configured trusted bootstrap and render scripts are explicitly launched; uploaded embedded Python
does not auto-execute.

## Results and retries

Results appear under their scene with the frame, job, Pod, backend, hardware, samples, and render
time. Multiple jobs can render the same frame without overwriting previous results.

- Download individual PNGs or ZIPs containing PNGs and JSON metadata.
- Preview frames as WebP thumbnails up to 720×480.
- Cancel a render to stop Blender and its child processes; completed results remain available.
- Retry failed, canceled, or interrupted jobs to render only their missing frames.

Each stored result contains `frame.png`, `preview.webp`, and `metadata.json`. Retrying reuses only
that job's verified results. Jobs remain owned by the Pod that created them.
