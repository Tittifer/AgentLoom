---
name: skills
description: Use when implementing, testing, or reviewing AgentLoom features.
---
# AGENTS.md

## Core Principles

1. Use the smallest necessary change by default.  
   Only modify code directly related to the current request. Do not expand scope, perform opportunistic refactors, or edit unrelated files.

2. Minimal change does not mean a temporary patch.  
   Prefer the most direct, local, and clear modification.  
   When a simple inline change matches the existing style, do not introduce extra indirection, temporary variables, wrapper functions, adapters, or speculative extensibility.

3. Prefer existing interfaces, methods, utilities, components, and code style.  
   Before adding a new interface, method, configuration option, dependency, or abstraction, check whether the existing implementation can satisfy the requirement.

4. Do not perform large refactors without permission.  
   Do not proactively change architecture, directory structure, naming systems, module boundaries, state management, data models, public APIs, or UI design language.

5. Preserve existing behavior.  
   Unless explicitly requested, do not change existing business logic, external behavior, configuration formats, API responses, or data structures.

## Working Process

6. Do not modify code unless the user explicitly asks for implementation.  
   If the user is only proposing an idea, asking about feasibility, requesting analysis, debugging guidance, design review, or comparing options, first provide at most three possible approaches.  
   For each approach, briefly explain:
   - Pros
   - Cons
   - Negative impact
   - Smallest viable change

7. Only enter the code modification phase when the user clearly asks to implement, modify code, fix, edit, patch, or apply a solution.

8. If the requirement is unclear, do not write code immediately.  
   First clarify the intended behavior, inputs and outputs, edge cases, error handling, and impact scope.

9. For small and clearly scoped changes:
   - Make the relevant code changes directly
   - Run the smallest relevant check
   - Summarize what changed and what was verified

10. For complex, ambiguous, or multi-file changes:
    - Read the relevant files first
    - Write a short implementation plan before editing
    - Prefer incremental changes over broad rewrites
    - Do not modify unrelated code
    - Do not introduce new patterns unless necessary

## Reading and Modifying Code

11. Before modifying a file, read enough surrounding context.  
    This includes nearby code, call sites, related utilities, existing components, and local style.

12. Before changing public functions, exported components, shared utilities, or public interfaces, inspect relevant usages.

13. Determine the impact scope before editing.  
    Prefer the smallest modification point and avoid spreading changes across modules.  
    If multiple files must be changed, explain why each file needs to change.

14. Do not keep code that is clearly obsolete after the current change.  
    If variables, code blocks, methods, branches, or old flows are directly replaced by this change, remove them.  
    Do not clean up historical code unrelated to the current request.

15. Do not introduce extensibility without an actual need.  
    Do not add abstractions, configuration options, strategy classes, callbacks, plugin mechanisms, or complex data structures just because they might be useful later.

16. Match the existing code style.  
    Naming, typing, logging, exceptions, directory structure, and comments should follow the current project.  
    Do not proactively change style unless the existing style clearly causes errors.

## Debugging Rules

17. When debugging, try to reproduce the issue first.

18. Fix the root cause, not only the visible symptom.

19. Do not delete tests, weaken type checks, disable lint rules, swallow exceptions, or change business semantics just to make the issue disappear.

20. If multiple reasonable fixes exist, choose the one most consistent with the current codebase and with the lowest intrusion. Briefly explain the tradeoff.

## Error Handling and Logging

21. Do not handle errors silently.  
    Do not swallow exceptions, use empty catch blocks, pretend a failed operation succeeded, or hide errors behind default values.

22. For unexpected states, throw errors directly so problems surface early.  
    Do not add automatic downgrade behavior, automatic retries, default fallbacks, or ignore logic unless explicitly requested.

23. Application errors and unexpected exceptions must be recorded through the project’s existing logging system.  
    Do not use `print`, `console.log`, or temporary debug output for error handling unless that is the project’s established convention.

24. Normal CLI output or user-facing output may use the project’s existing output mechanism.

25. Only catch exceptions when there is clear business meaning.  
    After catching an exception, handle it meaningfully, such as adding context and rethrowing, converting it into a clearer business exception, or performing recovery logic explicitly requested by the user.

26. Never log secrets, tokens, passwords, credentials, or sensitive data.

## Testing and Verification

27. Before finishing, run the smallest relevant checks that prove the change works.

28. For frontend changes, prefer running:
    - Type checking
    - Linting
    - Relevant tests
    - End-to-end tests only when the user flow changes

29. For backend changes, prefer running:
    - Relevant unit or integration tests
    - Type checking if applicable
    - Careful verification of queries, migrations, or schema changes when database code is changed

30. Do not run long full test suites by default unless the user asks or the impact scope is large.

31. If checks cannot be run, clearly state why in the final response.

32. Do not fabricate verification results.  
    Only claim that tests, type checks, linting, builds, or manual verification passed if they were actually run.

33. If a check fails, report the failure directly.  
    Do not hide, ignore, or work around the failure unless the user explicitly requests a temporary workaround.

## Files, Encoding, and Commands

34. Always read and write text files using UTF-8.

35. Set console output encoding to UTF-8.

36. When running PowerShell commands, prefer `login:false` to avoid loading user profile scripts unless explicitly needed.

37. Do not modify generated files unless the current task explicitly requires it.

38. Do not modify lockfiles unless a dependency change was explicitly requested and is actually necessary.

## Dependencies and Configuration

39. Use the package manager already used by the project.  
    Do not switch package managers.

40. Do not add production dependencies unless the user explicitly allows it.  
    Before adding a dependency, check whether the project already has an equivalent utility or implementation.

41. Do not update unrelated dependencies.

42. Do not hardcode secrets, tokens, API keys, passwords, credentials, private URLs, or machine-specific paths.

43. Do not modify `.env`, `.env.local`, or production configuration files unless explicitly requested.

44. If a new configuration value is truly needed, describe the variable name, purpose, and expected format.

## Protecting Existing Work

45. Before editing, check the current diff or file state when possible.

46. Do not overwrite existing user changes unrelated to the current task.

47. If a file already contains unrelated modifications, preserve them.

48. If the request conflicts with existing uncommitted changes, stop and ask the user.

49. Never run destructive git commands such as `reset`, `checkout`, `clean`, or `rebase` unless explicitly instructed.

## Ask First Before

Always ask the user before performing any of the following:

- Large refactors
- Database schema or migration changes
- Authentication, authorization, payment, or security-related changes
- Adding production dependencies
- Changing public APIs
- Changing configuration formats
- Changing data models
- Deleting or renaming many files
- Bulk formatting, bulk renaming, or large-scale code movement

## Never Do

Never:

- Modify code without an explicit implementation request
- Modify unrelated code
- Change business semantics just to make tests pass
- Delete tests to make the test suite pass
- Ignore type errors, disable lint rules, or swallow exceptions
- Use complex abstractions to hide a simple problem
- Use a temporary workaround instead of a direct fix unless explicitly requested
- Add unrequested features
- Rewrite unrelated modules
- Silently delete user code
- Change external behavior without explanation

## Final Response

When code has been changed, the final response must include:

- Files changed
- Behavior changed
- Whether old logic was removed
- Checks run and their results
- Checks not run and why
- Compatibility impact, risks, assumptions, or follow-up work

A task is complete only when:

- The requested behavior has been implemented
- Relevant checks pass, or the reason for not running them is stated
- No unrelated files are changed
- Errors are fixed rather than hidden
- Risks, assumptions, and follow-up work are clearly stated
