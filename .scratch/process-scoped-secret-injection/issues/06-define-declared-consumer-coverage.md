# Define declared consumer coverage

Type: grilling
Status: resolved

## Question

What does coverage of terminal and application launches guarantee?

## Answer

Verified PATH shims cover name-based launches. Explicit application
configuration binds integrations that do not rely on PATH. Absolute binary
paths are an intentional escape hatch, and diagnostics report unsupported or
bypassing bindings.
