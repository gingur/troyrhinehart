# troyrhinehart

troyrhinehart.com — personal site (Astro + React islands + Tailwind 4, deployed to Cloudflare Workers Static Assets).

> **v1 scaffold.** The landing page is an intentionally placeholder card. Real design, bio, and copy land in later specs.

## Stack

- [Astro 5](https://astro.build) — `output: 'static'` (SSG, no adapter)
- [@astrojs/react](https://docs.astro.build/en/guides/integrations-guide/react/) — islands on demand
- [Tailwind 4](https://tailwindcss.com) via `@tailwindcss/vite`
- `<ClientRouter />` (`astro:transitions`) for SPA-feel navigation
- Cloudflare Workers Static Assets (via `wrangler`)
- Shared configs + CI/deploy workflows from [`@gingur/devkit`](https://github.com/gingur/devkit) (pinned `@main`)

## Local development

Node version is pinned in `.nvmrc`; pnpm in `package.json` `packageManager`.

```sh
pnpm install
pnpm dev        # local dev server
pnpm build      # static build → dist/
pnpm preview    # preview the built site
pnpm lint       # eslint (devkit config)
pnpm typecheck  # astro check
```

## CI / Deploy

- **CI** (`.github/workflows/ci.yml`) — runs lint + typecheck + test on PRs via `gingur/devkit/.github/workflows/ci-node.yml@main`.
- **Deploy** (`.github/workflows/deploy.yml`) — on push to `main`, builds and deploys via `gingur/devkit/.github/workflows/deploy-cf-worker.yml@main`. Cloudflare credentials are fetched at runtime from Infisical using GitHub OIDC — **there are no Cloudflare secrets stored in GitHub.**
