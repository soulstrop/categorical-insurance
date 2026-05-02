# transform/role/catins-tokeniser
#
# The role catins.privacy.tokenisation references at the production
# tier. Add a transformation to this list whenever a new direct-PII
# field is annotated in catins.models and gets a corresponding
# `transformations/<field>.hcl`.
#
# Apply: vault write transform/role/catins-tokeniser @catins-tokeniser.hcl

transformations = ["holder_name"]
