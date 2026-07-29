Type: research
Status: resolved

## Question

What exact current Proton Pass agent, PAT, grant, audit-reason, session,
expiration, renewal, and revocation contracts constrain enrollment, unattended
recovery, and one-command rotation?

## Answer

An agent is an audited PAT and cannot administer or renew itself. Renewal
preserves grants but invalidates the old token immediately, so reliable host
rotation must overlap two distinct agents and use a full-user control-plane
session. Automated reads supply a non-secret `PROTON_PASS_AGENT_REASON`;
provider sessions persist locally, but Linux's default kernel-keyring key is
lost at reboot. The remaining first-party ambiguity is whether renewal, expiry,
deletion, and grant revocation immediately invalidate sessions already issued
from the PAT.

See [the Proton agent/PAT lifecycle report](../research/proton-agent-lifecycle.md).
