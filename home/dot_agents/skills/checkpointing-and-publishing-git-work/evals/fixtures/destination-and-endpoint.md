# Raw scenario

The branch has `branch.*.pushRemote`, remote push URLs differ from fetch URLs, and one URL is rewritten by Git config. Choose the effective push destination using Git's configuration precedence, then consider these independent immediate pre-push reruns of a reviewed `ready` plan:

- `destination.endpoint_fingerprint` changes while every non-destination plan field stays unchanged;
- `destination.config_digest` and `destination.endpoint_fingerprint` stay unchanged while `source_sha`, lease, or refspec changes;
- the entire rerun plan, including all destination and non-destination fields, is identical to the reviewed `ready` plan.
