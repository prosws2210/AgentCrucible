# AgentCrucible website

Landing page for AgentCrucible: Next.js 16 (App Router), Tailwind CSS v4, static export.

All numbers, trajectories and findings on the page come from real runs of the bundled example
(`src/data/runs.json` is extracted from `examples/support-agent/.crucible/runs/`).

```bash
npm install
npm run dev        # http://localhost:3000
npm run build      # static site in out/
```

## Deploying to GitHub Pages

`.github/workflows/pages.yml` builds with `NEXT_PUBLIC_BASE_PATH=/<repo>` and deploys `out/` on every push to
`main` that touches `website/`. One-time setup: **Settings → Pages → Source: GitHub Actions**.

## Structure

```
src/app/page.tsx                 all sections
src/app/layout.tsx               fonts (Geist, Geist Mono, Instrument Serif) + metadata
src/app/globals.css              theme tokens (ink / ember palette)
src/components/Terminal.tsx      animated CLI output (client)
src/components/TrajectoryViewer  v1 vs v2 recorded episode (client)
src/data/runs.json               real trajectories + comparison
```
