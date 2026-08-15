# Publishing the AgenticLogger SDKs

All three publish targets are **dry-run validated** from a clean checkout.
No registry tokens live in this repo (security: it is public). Supply your own
credentials at publish time.

| Target | Package | Artifact | Dry-run command (passes ✅) |
|--------|---------|----------|------------------------------|
| **crates.io** | `agentic-logger` (Rust) | `sdks/rust` | `cargo publish --dry-run --allow-dirty` |
| **npm** | `agentic-logger` (TS/JS) | `sdks/ts` | `npm pack` (see `dist/` after build) |
| **PyPI** | `agentic-logger` (Python) | repo root | `uv build` → `dist/*.whl` + `*.tar.gz` |

## crates.io (Rust)

```bash
cd sdks/rust
cargo publish --dry-run          # validates metadata + builds the crate
# actual publish (needs ~/.cargo/credentials.toml or CARGO_REGISTRY_TOKEN):
cargo publish
```

Set the token once: `cargo login <CRATES_IO_TOKEN>` (writes `~/.cargo/credentials.toml`,
never committed). Verified clean package contents: `Cargo.toml`, `src/*.rs`,
`examples/rust_emit.rs`, `README.md`.

## npm (TypeScript / JavaScript)

```bash
cd sdks/ts
npm install                      # brings dev deps (typescript)
npm run build                    # tsc → dist/*.js + *.d.ts
npm pack                         # inspect agentic-logger-0.1.0.tgz
# actual publish (needs `npm login` or NPM_TOKEN in .npmrc):
npm publish --access public
```

For CI publish, set `NODE_AUTH_TOKEN` and run `npm publish` in a
`setup-node` step with `registry-url: https://registry.npmjs.org`.

## PyPI (Python, reference package)

```bash
uv build                         # → dist/agentic_logger-0.1.0-py3-none-any.whl + .tar.gz
uv run twine check dist/*        # optional metadata lint
# actual publish (needs PyPI API token):
uv run twine upload dist/* -u __token__ -p <PYPI_TOKEN>
```

The sdist is lean (~250 KB) — `temp/`, `logs/`, `sdks/`, `research_reports/`
are excluded via `[tool.hatch.build.targets.sdist]` in `pyproject.toml`.

## CI publishing

`.github/workflows/release.yml` publishes all three targets on version tags —
**the git tag is the single source of truth** for the version (it syncs the
version into each manifest before building). Trigger a release with:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Add these secrets in GitHub → Settings → Secrets and variables → Actions
(never commit them — the repo is public):

| Secret | Registry | Token source |
|--------|----------|--------------|
| `NPM_TOKEN` | npm | https://www.npmjs.com → Access Tokens |
| `PYPI_TOKEN` | PyPI | PyPI → Account → API tokens (scope: agentic-logger) |
| `CARGO_REGISTRY_TOKEN` | crates.io | https://crates.io/settings/tokens |

PyPI can alternatively use **trusted publishing** (OIDC, no token): enable it
under PyPI → Project → Publishing → Add a new trusted publisher for this
repo + `release.yml` workflow, then delete the `password:` line in the
`publish-pypi` job.
