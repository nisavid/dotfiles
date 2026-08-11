# Define parity and the active harnesses

Type: grilling
Status: resolved

## Question

What does parity mean, and which harnesses must the first program cover?

## Answer

The active harnesses are global Claude Code, Codex, and Cursor. Parity means
that the coverage matrix records exactly one harness coverage outcome for every
cataloged equipment identity and active harness: `managed_provider`,
`manually_managed_provider`, `intentional_omission`, or `unsupported`. It does
so through one complete harness coverage record: provider outcomes include the
provider selection and every active-route record; omission and unsupported
outcomes include `no_provider`. Parity does not require identical packaging or
artifacts when harness capabilities differ. Operation dispositions are recorded
separately for every active provider route.
