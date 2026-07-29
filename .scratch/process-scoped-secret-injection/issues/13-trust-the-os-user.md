# Trust the logged-in OS user

Type: grilling
Status: resolved

## Question

Is a malicious process running as the logged-in OS user inside the isolation
threat model?

## Answer

No. Treat the OS account and provider session as trusted. Enforce declared
bindings as fail-closed misuse protection, while claiming containment only
against ambient inheritance, accidental misbinding, logs, and unrelated child
processes.
