Type: grilling
Status: resolved

## Question

Where should the host-agent PAT be resolved from the native credential store?

## Answer

Resolve it inside an internal session layer used by `secretctl` and lazy
recovery. Do not represent the bootstrap token as a consumer profile or expose
native credential-store locators in `secret-exec`.
