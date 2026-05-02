# Vault policy: catins-tokeniser
#
# Grants the catins production client only encode + decode on the
# catins-tokeniser role's transformations. No write access to the
# transformations / role themselves — those are admin-tier operations
# applied from this `vault/` tree.
#
# Apply: vault policy write catins-tokeniser catins-tokeniser.hcl

path "transform/encode/catins-tokeniser" {
  capabilities = ["update"]
}

path "transform/decode/catins-tokeniser" {
  capabilities = ["update"]
}
