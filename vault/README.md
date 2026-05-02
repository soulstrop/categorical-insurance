# `vault/` — configuration-as-code for the production Vault server

This tree is the source of truth for the HashiCorp Vault setup that
backs the *production* tier of `catins.privacy.tokenisation` per
ADR 006 §2. None of these files run locally — the dev tier uses the
`MockTokenisationClient`, which is an in-process deterministic stub —
but they document exactly what would be applied to a real Vault
server before production data flows.

## Tree

* `transformations/` — Vault Transform engine definitions, one per
  PII field (or class of fields with shared format). Each `.hcl`
  binds a transformation name to an FPE template. Applied via:

      vault write transform/transformations/<name> @<file>.hcl

* `roles/` — Vault Transform roles. A role bundles one or more
  transformations and is the unit that catins-side code references
  when calling encode/decode. Applied via:

      vault write transform/role/<name> @<file>.hcl

* `policies/` — Vault policy documents that grant capabilities on the
  Transform engine paths. Applied via:

      vault policy write <name> <file>.hcl

## Environment expectations

The operator applying these files must have:

* `VAULT_ADDR` set to the Vault server URL.
* `VAULT_TOKEN` with sufficient privilege to write transformations,
  roles, and policies (typically a root or admin token, *not* the
  catins-tokeniser token).

The catins-tokeniser token issued downstream is what
`catins.privacy.tokenisation`'s production client uses; it has only
the encode/decode capabilities granted by `policies/catins-tokeniser.hcl`.

## Coverage

Today only individual-holder names are tokenised at the proposal-level
boundary (per the ADR 006 §1 PII classification — direct-PII
strings). When new direct-PII fields land (SSN, account numbers,
etc.), the pattern is:

1. Annotate the field in `catins.models` with `PII("direct", …)`.
2. Add a `transformations/<field>.hcl` here.
3. Reference it from `roles/catins-tokeniser.hcl`'s
   `transformations` list.
4. The classification report (`//python:privacy:classify`) and the
   compat-check (`//python:schema:compat-check`) verify the
   end-to-end consistency.
