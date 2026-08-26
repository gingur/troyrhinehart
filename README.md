# troyrhinehart

troyrhinehart.com — personal site (Astro + React islands + Tailwind 4, deployed to Cloudflare Workers Static Assets).

> **v1 scaffold.** The landing page is an intentionally placeholder card. Real design, bio, and copy land in later specs.

## Resume

The resume is published two ways, both linked from the landing page:

- **`/resume`** — HTML resume rendered from `src/data/resume.ts`. Responsive, indexable
  (includes `Person` JSON-LD), and carries print styles so browser Print produces a clean
  light-mode copy.
- **`/resume.pdf`** — the source PDF in `public/`, offered as a download from
  the HTML page.

`src/data/resume.ts` mirrors the PDF. **When the PDF is refreshed, replace
`public/resume.pdf` and update `src/data/resume.ts` in the same commit** so the
two do not drift. The phone number printed on the PDF is deliberately left out of the HTML
page — that page is crawlable plain text, so email and LinkedIn are the contact channels on it.

### Why `/resume.pdf` carries a canonical header

The PDF is text-based, so Google indexes it independently of `/resume/` and the two compete
as duplicate content. [Google's documented fix for non-HTML documents](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)
is a `rel="canonical"` **HTTP response header**, which consolidates ranking signals onto the
HTML page. `public/_headers` sets it via
[Workers Static Assets custom headers](https://developers.cloudflare.com/workers/static-assets/headers/):

```
/resume.pdf
  Link: <https://troyrhinehart.com/resume/>; rel="canonical"
```

That URL must stay **byte-identical** to the `<link rel="canonical">` that `BaseLayout` emits
for the resume page — trailing slash included. Astro builds directory-style routes, so the
canonical is `/resume/`, not `/resume`. If the route format or the site URL ever changes,
`public/_headers` has to change with it.

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

<!-- credential-split green check 2026-07-13 -->
