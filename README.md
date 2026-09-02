# BlendRender

Render Blender projects on RunPod from a web dashboard. Upload a `.blend` file or a project ZIP,
choose a frame or range, and download the results. Connect multiple Pods to one network volume to
share scenes and render in parallel.

- Resume interrupted uploads, including after a page reload.
- Use scene settings or adjust samples, tile size, and resolution for each render.
- Track progress, preview frames, and download PNGs with render metadata.
- Keep completed frames when canceling or retrying a job.
- Compare results from different Pods without overwriting earlier renders.

## RunPod quick start

1. Build and publish the image for `linux/amd64`:

   ```bash
   git submodule update --init --recursive
   docker buildx build --platform linux/amd64 -t YOUR_REGISTRY/blendrender:2.1.0 --push .
   ```

2. Create an RTX RunPod Pod using the image, attach a network volume at `/workspace`, expose HTTP
   port `8000`, and set a long, random `APP_PASSWORD`. Keep `COOKIE_SECURE=true` for HTTPS.

3. Open `https://POD_ID-8000.proxy.runpod.net`, sign in, upload a scene, and select **New render**.

For parallel rendering, attach the same volume to additional Pods running the same image version
and password. Each Pod renders its own jobs, one at a time; all dashboards share scenes and results.

See [Deployment](docs/deployment.md) for storage requirements and configuration. BlendRender is
designed for trusted users; read [Security](docs/security.md) before exposing it.

## Documentation

- [Scene preparation and rendering](docs/rendering.md)
- [Deployment and operations](docs/deployment.md)
- [RunPod S3 scripts guide](docs/s3-guide.md)
- [HTTP API](docs/api.md)
- [Security](docs/security.md)
- [Development and testing](docs/development.md)
- [Architecture](docs/architecture.md)
- [Documentation index](docs/README.md)
