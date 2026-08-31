# BlendRender

BlendRender is a shared-workspace Blender renderer for RunPod Pods. Upload a `.blend` file or a
self-contained project ZIP once as a **scene**, then create independent render **jobs** from that
scene on any connected Pod. The dashboard transfers projects in resumable chunks (8 MiB by default), so a lost
proxy connection or page reload can continue an in-progress upload. Each Pod renders only the jobs
created through its dashboard, while all Pods display the same scenes and every published result
variant.

Results are immutable scene assets. Rendering the same scene/frame on multiple Pods preserves every
PNG/WebP variant along with backend, hardware, samples, pod, and render-duration metadata.

## RunPod quick start

1. Build and publish the Linux image:

   ```bash
   docker buildx build --platform linux/amd64 -t YOUR_REGISTRY/blendrender:2.1.0 --push .
   ```

2. Create one or more Secure Cloud Pods from that image, attach the **same network volume** to each,
   expose port `8000`, and set the same long `APP_PASSWORD`.

3. Open any Pod dashboard, upload a scene, then create a render job. Open a second Pod dashboard to
   create another job for the same scene when parallel rendering is needed.

The shared catalog defaults to `/workspace/blendrender`. Read [Deployment](docs/deployment.md) and
[Security](docs/security.md) before exposing the service.

## Local development

```bash
cp .env.example .env
just install
just dev-backend
just dev-frontend
```

Local development uses `./workspace` and Pod ID `local`. Run checks with:

```bash
just test
just check
```

## Documentation

- [Architecture](docs/architecture.md)
- [HTTP API](docs/api.md)
- [Development and testing](docs/development.md)
- [Deployment and operations](docs/deployment.md)
- [Security](docs/security.md)
- [Rendering](docs/rendering.md)
