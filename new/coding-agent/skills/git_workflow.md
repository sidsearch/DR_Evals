# Skill: git_workflow

Follow these steps for any task that involves committing code or working with branches.

## Before making changes
1. Run `git status` to see the current state of the working tree.
2. Run `git branch --show-current` to confirm which branch you are on.
3. If the task is a new feature or fix, create a branch: `git checkout -b <descriptive-name>`.
   - Never commit directly to main/master unless explicitly asked.

## Making changes
4. Make the smallest change that satisfies the requirement.
5. After each significant change, run the test suite to catch regressions early.
   - Look for: `pytest`, `npm test`, `make test`, or check for a Makefile/package.json.

## Committing
6. Stage only the relevant files: `git add <specific files>` — never `git add .` or `git add -A`.
7. Review the diff before committing: `git diff --staged`.
8. Write a commit message in imperative mood, under 72 characters, that explains WHY:
   - Good: "Fix off-by-one in pagination offset calculation"
   - Bad: "Fixed bug" / "changes" / "update"
9. Never use `--no-verify`, `--force`, or `--no-gpg-sign` unless explicitly asked.

## After committing
10. Run `git log --oneline -5` to confirm the commit looks right.
11. If tests exist, run them one final time on the committed state.
