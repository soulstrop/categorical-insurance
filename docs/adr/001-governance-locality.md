# ADR 001: Data Locality for Governance Evaluation

## Status
Accepted

## Context
The Haskell categorical insurance project (`hx`) enforces a strict boundary between `Proposals` and `Contracts` using a `validate` function. In our architecture, this validation logic (the Governance comonad) is implemented using Open Policy Agent (OPA) and the Rego policy language.

OPA is typically deployed as a standalone REST API sidecar. However, our primary data store and compute engine is Snowflake. If we query millions of proposals from Snowflake, pull them across the network into a Python runtime, serialize them to JSON, send them to an external OPA endpoint, and push the results back, we will destroy Snowflake's "data gravity". This would introduce severe network latency, egress costs, and security risks.

We need a way to run Rego evaluations while maintaining zero data-movement.

## Options Considered

1. **External OPA Server:**
   * *Pros:* Standard deployment model, easy to debug.
   * *Cons:* Breaks data locality, massive data egress/ingress, slow for batch processing.
2. **Snowpark Container Services (SPCS) running OPA:**
   * *Pros:* Runs the official OPA Docker image inside Snowflake's security perimeter. No external egress.
   * *Cons:* Requires managing SPCS compute pools, adds operational complexity for what should be a pure functional evaluation. Data still moves from the warehouse nodes to the container nodes.
3. **Snowpark Python UDFs (Embedded Rego):**
   * *Pros:* True zero-data movement. Python UDFs run directly on the virtual warehouse nodes where the data resides. We can use a Python Rego evaluator (like `regorus` or WebAssembly compilation) packaged inside the UDF.
   * *Cons:* May require polyfill or strict control over the Rego runtime environment within the Snowflake sandbox.

## Decision
We will use **Option 3: Snowpark Python UDFs (Embedded Rego)**.

We will package our Rego policies (`policies/*.rego`) alongside a Python Rego evaluator into a Snowflake Vectorized UDF. The `validate` step will be executed as a simple SQL/Snowpark query (e.g., `SELECT validate_policy(proposal_data) FROM proposals`), allowing Snowflake to distribute the policy evaluation across its compute cluster natively.

## Consequences
* **Positive:** Unbeatable performance for batch governance checks. Data never leaves the Snowflake warehouse. Complete adherence to the "bring compute to the data" philosophy.
* **Negative:** We cannot use the standard OPA HTTP API. We are constrained to Python packages that can evaluate Rego and fit within Snowflake's UDF limitations.
