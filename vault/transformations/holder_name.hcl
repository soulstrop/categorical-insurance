# transform/transformations/holder_name
#
# Format-preserving encryption (FPE) for individual-holder names. The
# alphanumeric template means: a 5-letter input (e.g. "Alice") yields
# a 5-letter ciphertext of the same character class. This matches the
# alphabet-preservation contract MockTokenisationClient implements at
# the dev tier.
#
# Apply: vault write transform/transformations/holder_name @holder_name.hcl

type         = "fpe"
template     = "builtin/alphanumeric"
tweak_source = "internal"
allowed_roles = ["catins-tokeniser"]
