# Skill: refactor_module

Follow these steps when refactoring an existing module or file.

## Before touching anything
1. Read the full file first — never edit without reading the whole thing.
2. Identify all call sites before renaming anything:
   - `grep <old_name> . --include="*.py"` (or the relevant extension)
3. Use `task_create` to list each distinct change you plan to make.

## Making changes
4. One logical change at a time — do not combine unrelated edits in a single step.
5. After each rename: grep for the old name to confirm no stale references remain.
6. After each structural change (moving functions, changing signatures): run the type checker.
   - Python: `mypy <file>` or `pyright <file>`
   - TypeScript: `tsc --noEmit`
7. Run the test suite after each significant change, not only at the end.

## Multi-location edits
8. If the same pattern must change in many places, use `edit_file` with `replace_all=true`
   when the replacement is unambiguous.
9. For complex multi-file refactors, batch reads first (read all affected files), then
   make writes — this avoids reading a file you just edited mid-refactor.

## Finishing up
10. Run the full test suite one final time.
11. Remove any dead code that the refactor made unreachable.
12. Update `task_update` statuses as you complete each step.
