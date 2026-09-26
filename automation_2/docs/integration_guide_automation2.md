# Extending the prototype to a real company

The prototype keeps the business logic separate from vendor integrations.

The application talks to five small interfaces:

- `PartnerDirectory` — supplier and business-partner master data
- `ContractSystem` — contract search and status
- `DocumentStore` — controlled documents
- `WorkflowSystem` — case, approval, and submission
- `AuditStore` — audit events

The demo uses `SQLiteStore` with mock adapters. In a real company, those adapters would be replaced with approved integrations while the MCP tools remain unchanged.

## Reference enterprise stack

A realistic implementation can map these interfaces to systems already used for the same business functions. For example:

| Business capability | Reference product | Adapter interface |
|---|---|---|
| Supplier master and ERP | SAP S/4HANA | `PartnerDirectory` |
| Source-to-contract and contract workspace | SAP Ariba Contracts | `ContractSystem` |
| Intake, case workflow, and approval | ServiceNow Contract Management | `WorkflowSystem` |
| Controlled contract documents | Microsoft SharePoint | `DocumentStore` |
| Contract lifecycle and signing | Docusign CLM and eSignature | `SignatureProvider` |

These are reference choices, not mandatory dependencies. A company could use Oracle, Coupa, Icertis, Salesforce, an internal ERP, or another approved system by implementing the same interface contract.

## Deployment pattern

For local development, the SDK uses stdio.

For a deployed service, use Streamable HTTP and place the server behind the company's normal identity layer, gateway, and monitoring stack.

Production identity should come from the transport and authentication layer. The model must never be trusted to invent an approver identity or authorization role.

## Reliability pattern

For operations that make real changes to business data:

1. Validate everything before making the change.
2. Create a durable case with a unique idempotency key.
3. Require explicit human approval for governed actions.
4. Pass the idempotency key to the downstream system.
5. Record the downstream reference.
6. Reconcile the result.
7. Make retries safe.

The demo already implements the case state machine and mock idempotency. Completing the downstream adapter is the remaining integration step needed for a production system.
