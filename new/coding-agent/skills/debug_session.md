# Skill: debug_session

Follow these steps to debug a failing test, error, or unexpected behavior.

## Understand the failure first
1. Read the full error output carefully — note the exact error message, exception type,
   and the file + line number where it originates.
2. Do NOT guess or change code before you understand the failure.

## Gather context
3. Read the failing file at the error line, plus ~20 lines of surrounding context.
4. Check recent changes: `git log --oneline -10` and `git diff HEAD~1 -- <file>`.
5. Reproduce with the smallest possible command:
   - For tests: `pytest path/to/test_file.py::test_name -xvs`
   - For scripts: run with minimal inputs

## Form a hypothesis
6. State your hypothesis before changing anything. It should explain both the symptom
   and the root cause (not just "something is wrong with line X").

## Fix
7. Change one thing at a time. Re-run the reproducer after each change.
8. Never remove a failing test or add `# type: ignore` / `@ts-ignore` to make an error
   disappear — fix the underlying problem.
9. If the fix is non-obvious, add a one-line comment explaining the WHY (not the WHAT).

## Verify
10. Confirm the fix with the full test suite, not just the previously failing test.
11. Check that the fix doesn't regress related functionality.
