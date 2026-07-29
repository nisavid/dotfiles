Type: grilling
Status: resolved

## Question

How should host-agent bootstrap tokens rotate before mandatory expiration?

## Answer

Monitor expiry and notify at defined thresholds. Rotate through one explicit,
verified `secretctl` command, retaining the old token until the replacement
works whenever Proton's contract permits.
