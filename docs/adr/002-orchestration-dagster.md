# ADR 002: Orchestration Framework - Dagster vs. Snowflake Tasks

## Status
Accepted

## Context
Our architecture requires coordinating multiple distinct execution environments:
1. `dbt` for SQL-based feature engineering and data preparation.
2. `Snowpark Python` for executing the Learner pipelines (implement, update, request).
3. `Snowpark UDFs` for applying Rego governance policies.

We need an orchestration layer to ensure these steps happen in the correct sequence, manage the dependencies between them, and track the state of our machine learning models.

## Options Considered

1. **Snowflake Tasks & Task Graphs:**
   * *Pros:* Native to Snowflake, zero external infrastructure required.
   * *Cons:* Imperative "task-based" mental model. Hard to integrate with `dbt` cleanly without wrapping everything in stored procedures. Impossible to test the orchestration logic locally without deploying to a Snowflake environment. Poor visibility into the state of the data itself.
2. **Dagster:**
   * *Pros:* Software-Defined Asset (SDA) model aligns perfectly with our categorical architecture. An intermediate type (like a Learner's State $s$ or a `Proposal`) maps directly to a Dagster Asset. First-class support for `dbt` and Python ML pipelines in the same graph. Excellent local testing story.
   * *Cons:* Requires running Dagster infrastructure (or using Dagster Cloud) outside of Snowflake.

## Decision
We will use **Dagster**.

The categorical foundations of this project are obsessed with tracking *types* and *states* (the state of the Learner, the Proposal, the Governed context, the bound Contract). Dagster's SDA model natively understands this: it tracks the lineage of *data assets* rather than just the execution of *tasks*.

We will define our dbt models, Snowflake ML parameters, and Contract tables as Dagster Assets. Dagster will issue the remote commands to Snowflake to execute the work, but will act as the single pane of glass for the pipeline's structure.

## Consequences
* **Positive:** Deep observability. We can track exactly which version of the dbt models produced the data that trained a specific version of a Learner's state. We can test our pipeline orchestration locally.
* **Negative:** We introduce an external moving part (the Dagster daemon/webserver) that must be maintained and authenticated with Snowflake.
