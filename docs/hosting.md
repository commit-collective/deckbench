# Hosting the page

The page is plain files (`deckbench/ui`), so any static host can serve it. commitcollective.cc serves it from its own Cloudflare
worker, `deckbench-app`, defined by `wrangler.toml` in this repo. It has the route `commitcollective.cc/deckbench/app/*`, which takes
those addresses from the main site worker. The landing page at `/deckbench/` stays in the website's repo.

A push to main that changes `deckbench/ui` builds and deploys the worker, with no change to the website's repo.

## Setting it up on Cloudflare

1. Workers & Pages, Create, Import a repository, and choose this repo.
2. Worker name `deckbench-app`, the same as `name` in `wrangler.toml`.
3. Production branch `main`. Build command empty. Deploy command `npx wrangler deploy`.
4. Build watch paths: include `deckbench/ui/**`, `worker.js` and `wrangler.toml`.
5. After the first deploy, check Settings, Domains & Routes: `commitcollective.cc/deckbench/app/*` must be listed.
6. Open `/deckbench/app/?demo` and `/deckbench/app/` on the site.

## Seeing it on the website locally

The site's repo does not hold the page, so a local copy of the site has no `/deckbench/app/`. Copy it in for a look. The folder is
ignored by the site's git, so nothing is committed:

    python tools/copy_to_site.py ../commitcollective.cc/public/deckbench/app

Run it again after a change to the page. This is the same idea as `tools/release.py --preview` in the mods repo.

## To host it somewhere else

Copy the files with `python tools/copy_to_site.py DIR`, or point a static host at `deckbench/ui`. The page asks for the address
and token of a bench, or runs its demo with `?demo`. A bench must be started with `--allow-origin` for the page's address
(see [phone.md](phone.md)).
