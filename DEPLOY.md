# The `deploy` branch -- what it is, and how to change it

**Read this before touching this branch.** It is not a feature branch and it does not
behave like one.

`deploy` is an **assembly**: an upstream release with this fork's deviations merged on
top. It is what the deployment builds. It is never proposed upstream, and it is
**rebuilt rather than patched**.

This file must survive every rebuild. If you recreate the branch, re-add it -- a
recreate that drops it leaves the next person with no explanation at all.

---

## What goes into it

| Branch class | In `deploy`? |
|---|---|
| `fork/*` | **all of them.** These are the deviations the deployment exists to run |
| `feature/*` | **only the ones the deployment actually needs.** Not automatically all of them |
| `experiment/*` | never |
| `integration/*` | never |

At the time of writing the deployment needs five `feature/*` branches, not the full
set. Adding one that is not needed is not harmless: it widens the diff against
upstream for no operational reason, and every extra deviation is one more thing to
re-verify at the next upgrade.

## Two branches that must never be merged in

**`feature/remove-shadowing-next-config`.** It deletes `cognee-frontend/next.config.mjs`;
`fork/next-config` maintains that same file. They are deliberately opposite -- one is
the fix upstream should take, the other is how this fork is configured. Merging both
produces a modify/delete conflict, and "resolving" it either way breaks something.

**Anything under `experiment/`.** Long-lived exploratory work; not deployable.

## One ordering rule

If **both** `feature/mcp-only-context` and `feature/mcp-progress-notifications` are
included, merge **`feature/mcp-only-context` last**. They touch the same recall call
site: one adds an argument, the other wraps the call. The correct resolution keeps
**both** -- the wrapper around the full argument list, argument included:

```python
results = await _with_progress(
    cognee_client.recall(..., only_context=only_context),
    label="Recalling memory",
)
```

Merging in the other order invites a resolution that silently drops one of them.

One benign overlap to expect: `experiment/slm-lora` and `feature/gitignore-data-dir`
both append to `.gitignore`. Different sections; keep both.

---

## Rebuilding it

Rebuild; do not cherry-pick fixes onto the existing branch. A rebuild is cheap and
leaves an auditable assembly.

```bash
git fetch upstream main

git checkout -B deploy upstream/main

# 1. every fork/* branch
for b in $(git branch -r --list 'origin/fork/*' --format='%(refname:short)'); do
  git merge --no-ff -m "integrate: ${b#origin/}" "$b" || break
done

# 2. the feature/* branches the deployment needs -- list them explicitly,
#    and keep feature/mcp-only-context last if the progress branch is included
for b in feature/mcp-build-from-source \
         feature/remove-ts-expect-error \
         feature/gate-demo-on-dataset-status \
         feature/docs-fixes \
         feature/mcp-only-context ; do
  git merge --no-ff -m "integrate: $b" "origin/$b" || break
done

# 3. re-add this file if it is missing, and commit it
git add DEPLOY.md && git commit -m "docs: restore the deploy branch guide"

# 4. verify before pushing -- see below
git push --force-with-lease origin deploy
```

`--no-ff` is deliberate: one merge commit per branch means `git log --first-parent`
reads as an inventory of what is in the build, and any single branch can be backed out
with `git revert -m 1 <merge-sha>` while bisecting a failure.

## Verify before pushing

```bash
# Every fork/* branch actually landed
for b in $(git branch -r --list 'origin/fork/*' --format='%(refname:short)'); do
  git merge-base --is-ancestor "$b" deploy \
    && echo "ok   ${b#origin/}" || echo "MISSING ${b#origin/}"
done

# Nothing unintended came along: the file list should be the union of the
# merged branches and nothing else
git diff --name-only upstream/main deploy | wc -l

# The version the images will be tagged with
git show deploy:pyproject.toml | grep -m1 '^version'
```

That last line matters more than it looks. The image tag comes from `pyproject.toml`,
so re-anchoring this branch to a newer upstream release **changes the image version**,
and anything pinning the old tag stops resolving. Treat a version move as a deliberate
deployment change with its own testing -- not as a side effect of a rebuild.

## Updating for a new upstream release

1. Refresh each `fork/*` branch by **merging** `upstream/main` into it -- never
   rebasing; they are shared and published.
2. Check whether upstream has implemented any of them. When it has, **delete the
   branch** instead of carrying it. That is the goal: every deviation absorbed
   upstream is one less thing to maintain here.
3. Rebuild `deploy` from the refreshed branches.
4. Expect the image version to move, and plan for it.

## Adding a new deviation

Do not commit it here. Create a `fork/<slug>` branch from `upstream/main`, one concern,
with a commit body stating what changed, which files, and why upstream would not take
it -- then rebuild `deploy`.

If the change is something upstream might actually want, it is a `feature/*` branch
instead, and it should be re-cut onto `upstream/dev` and re-verified there as soon as
you think so. Upstream frequently turns out to have solved the problem already, and
that is much cheaper to discover early than at pull-request time.
