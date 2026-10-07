# Contributing to Cordia Short

This repository is private to the Cordia team and invited collaborators.

## Workflow

1. Clone: `git clone git@github.com:CordiaAI/Cordia-Short.git`
2. Branch from `master`: `git checkout -b <your-name>/<short-topic>` (for example `sam/fix-signin-copy`).
3. Commit and push your branch: `git push -u origin <your-name>/<short-topic>`.
4. Open a pull request into `master`. Vercel builds a preview deployment for the branch.
5. CI (`Tests`) must pass and a code owner must approve. Only then can the PR merge.
6. Merging to `master` deploys to production. Nobody pushes to `master` directly.

Before opening a PR, read [AGENTS.md](AGENTS.md) and [docs/CURRENT_BUILD_TRUTH.md](docs/CURRENT_BUILD_TRUTH.md).

## Secrets

- Never commit keys, tokens, passwords, promo or discount codes, or customer data, including in comments, tests, or docs.
- Local values go in `.env.local` (ignored by Git). Production values live in Vercel environment variables.
- If a secret is committed, tell the repository owner immediately. Rotate it first; deleting the commit is not enough.

## Running and testing

See [README.md](README.md).
