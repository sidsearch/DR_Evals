# Skill: code_review

Follow these steps when asked to review code for correctness, security, or quality.

## Read before commenting
1. Read every file being reviewed in full — never comment on a partial read.
2. Note the stated purpose of the change (PR description, task description, or user prompt).

## What to check
3. **Correctness**: logic errors, off-by-one, unhandled edge cases, wrong assumptions.
4. **Security**:
   - Injection risks (shell, SQL, HTML/JS) — especially when user input reaches `bash`,
     a query, or a template.
   - Hardcoded secrets or credentials.
   - Unsafe deserialization or `eval`-equivalent calls.
   - Path traversal when file paths come from external input.
5. **Error handling**: are errors at system boundaries (user input, API calls, file I/O)
   handled and reported cleanly? Are internal errors propagated faithfully?
6. **Performance**: N+1 patterns, unbounded loops, loading full files when pagination exists.
7. **Clarity**: misleading names, missing docstrings at public boundaries, dead code.

## How to report
8. Prioritize findings:
   - **Critical** — must fix before merging (security, data loss, crashes)
   - **Important** — should fix (correctness, significant performance)
   - **Minor** — nice to have (style, clarity)
9. For each issue: cite the exact file and line, explain WHY it is a problem,
   and suggest a concrete fix.
10. End with a one-paragraph summary: overall assessment and a count of blocking issues.
