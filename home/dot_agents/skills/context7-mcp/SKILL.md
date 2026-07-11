---
name: context7-mcp
description: Use when current public documentation is needed for a library, framework, SDK, API, CLI tool, or cloud service
---

# Context7 MCP

Use Context7 for current documentation about public libraries. Keep every external query public and minimal.

## Public Library Workflow

1. Call `resolve-library-id` with the public library name and only the minimum public technical question needed to select the correct documentation.
2. Select the closest official match, preferring a version-specific ID when the question names a version.
3. Call `query-docs` with that library ID and the same minimized public question.
4. Answer from the fetched documentation and identify the relevant version when useful.

Before either call, remove proprietary identifiers, internal package or service names, customer or incident data, credentials, code, and machine-local paths. Rewrite the query using generic public terminology rather than disclosing private context.

## Internal-Only Libraries

For internal-only libraries, use local source and documentation. Do not call Context7 or web search.

If local evidence is insufficient, report the specific gap and request authority before disclosing anything externally.
