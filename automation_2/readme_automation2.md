# Supplier \& Contract Operations Copilot — MCP Prototype

This is the second automation prototype built from the workflow-mining project.

The source logs showed a large `WORKFLOW\_006` family of repeated supplier, business-partner, and contract activities. These included supplier registration, contract-related procedures, and contract cancellation or termination. The cluster appeared 64 times across 10 sessions and accounted for about 26.2 minutes of recorded activity.

The logs do not reveal the company's actual production APIs, approval policy, required master-data fields, or complete business rules. This prototype therefore does not claim to reproduce the real internal system. Instead, it models the workflow in a realistic and extensible way: find business records, inspect contracts and documents, validate a request, prepare the required action, send it for human approval, and only then perform the downstream action.

## What the product does

The prototype acts as a small operations copilot for supplier and contract work.

A user could ask an AI assistant:

> "Check whether ABC Trading already exists. If it doesn't, tell me what is missing to register them and prepare a registration request."

The AI does not invent supplier data or make approval decisions. It uses MCP tools to interact with the business system, while the deterministic Python service handles validation, policy checks, and state changes.

The overall flow is:

1. The user sends a request.
2. The AI host or LLM interprets the request and selects the required MCP tools.
3. The business tools provide supplier, contract, document, case, and audit data.
4. Deterministic policy and risk checks validate the request.
5. The service creates a prepared case.
6. A human reviews and approves the case.
7. The approved action is submitted to the downstream system.

MCP provides the standard interface between the AI host and the business capabilities. The Python service remains responsible for business rules, validation, and state changes. The server is also designed for the MCP SDK worker-thread execution model: the SQLite demo store uses thread-local connections, a busy timeout, and WAL mode so concurrent tool calls do not reuse a connection created by the server's startup thread. The current official Python SDK exposes tools and resources and supports local stdio as well as Streamable HTTP for deployment.

## Why MCP is useful here

The value of MCP is not simply adding another interface in front of a Python function. The useful part is that the assistant can combine several business capabilities in one workflow:

* search for an existing partner;
* inspect related contracts;
* inspect supporting documents;
* check whether the request is complete;
* run policy and risk checks;
* prepare the appropriate request;
* send the request for human approval;
* submit it only after approval.

That combination is a much better fit for an AI tool interface than a single-purpose function.

## Reference enterprise systems

The prototype uses vendor-neutral interfaces, but the architecture maps naturally to established enterprise products:

|Capability|Reference product|Adapter in this repository|
|-|-|-|
|Supplier and business-partner master|SAP S/4HANA|`PartnerDirectory`|
|Source-to-contract and contract workspace|SAP Ariba Contracts|`ContractSystem`|
|Intake, case management, and approval|ServiceNow Contract Management|`WorkflowSystem`|
|Controlled documents|Microsoft SharePoint|`DocumentStore`|
|Contract lifecycle and signing|Docusign CLM and eSignature|`SignatureProvider`|

These are reference integrations, not mandatory dependencies. The choices are based on the capabilities documented by the vendors. 

## Vendor-neutral architecture

The core service does not contain vendor-specific SAP, ServiceNow, SharePoint, or Docusign logic.

Instead, it works through a small set of interfaces:

* `PartnerDirectory`
* `ContractSystem`
* `DocumentStore`
* `WorkflowSystem`
* `SignatureProvider`
* `AuditStore`

The demo uses mock implementations backed by SQLite.

A company can replace the adapters with its own approved integrations without changing the core tools or business logic. That keeps the prototype flexible and avoids coupling it to a single vendor.

## MCP tools exposed

### `search\_business\_partners`

Find likely supplier or business-partner records.

### `get\_business\_partner`

Return a partner's master record together with linked contracts and documents.

### `list\_partner\_contracts`

List all contracts for a partner, optionally filtered by status.

### `get\_contract`

Read a contract and its lifecycle information.

### `check\_request\_completeness`

Check whether a proposed request contains all fields required by the configured policy.

### `find\_duplicate\_candidates`

Look for possible existing suppliers before a new partner record is created.

### `assess\_contract\_request`

Run deterministic policy checks and return blocking findings, enhanced-review flags, duplicate candidates, and supporting evidence.

### `prepare\_contract\_case`

Create a durable case for a supplier or contract operation. Hard validation failures create a `BLOCKED` case.

### `request\_human\_approval`

Move a clean case to `PENDING\_APPROVAL`.

### `approve\_case`

Approve a case after human review.

### `submit\_case`

Perform the downstream action after approval. In the prototype, the downstream action is deliberately mocked and idempotent.

### `get\_case`

Return the current case, its findings, and the audit trail.

The server also exposes the policy resource `contract-ops://policy`.

## Request types supported

The architecture supports four common supplier and contract operations:

* `supplier\_registration`
* `contract\_creation`
* `contract\_amendment`
* `contract\_termination`

The policy is configuration-driven, so a company can change required fields and review thresholds without changing the business service.

## State machine

Each request moves through an explicit state machine:

`DRAFT` → `PENDING\_APPROVAL` → `APPROVED` → `SUBMITTED`

Hard validation failures enter `BLOCKED`.

A blocked case cannot be approved, and a case that has not been approved cannot be submitted.

## Important safety checks

The prototype adds controls around the parts of the workflow where an incorrect action could have a meaningful business impact.

### Duplicate supplier risk

Before supplier registration, the system searches the supplier master for possible duplicates.

**Impact:** a duplicate master record can create downstream purchasing, payment, or reporting problems.

**Mitigation:** duplicate detection is treated as a blocking or high-severity finding and requires human review.

### Missing required data

A request with missing required fields cannot proceed.

**Impact:** incomplete master data can cause failed onboarding or incorrect downstream records.

**Mitigation:** configuration-driven completeness checks run before approval.

### High-value contract changes

Large changes to an existing contract's annual value are surfaced for enhanced review.

**Impact:** an incorrect amendment can materially change spend or contractual exposure.

**Mitigation:** configurable percentage thresholds produce warning or high-severity findings while keeping final approval with a person.

### Contract termination with open obligations

Termination is blocked when the contract record reports open obligations.

**Impact:** terminating a contract too early can leave unresolved commitments or operational work.

**Mitigation:** the policy engine blocks the request until the dependency is resolved.

### Unauthorized submission

A request cannot be submitted directly from `DRAFT` or `PENDING\_APPROVAL`.

**Impact:** an AI agent or automation bug must not be able to turn a suggestion into an accounting or procurement action without authorization.

**Mitigation:** an explicit approval state is required before submission.

### Duplicate downstream action

A stable idempotency key is stored with the case and passed to the mock workflow system.

**Impact:** a retry after a timeout could otherwise create a duplicate downstream action.

**Mitigation:** repeated submission of the same approved case returns the same submission ID.

### Stale or unavailable integrations

The production adapter layer is designed to handle explicit integration failures rather than silently returning incomplete data.

**Impact:** a stale supplier or contract record could lead to an incorrect recommendation.

**Mitigation:** governed actions fail closed, the failure is recorded, and the request requires retry or reconciliation.

### LLM mistakes or prompt injection

The AI is treated as an untrusted caller of tools. It should not be trusted with business authorization, hidden credentials, or unrestricted write privileges.

**Impact:** an incorrect model action could create or change sensitive enterprise records.

**Mitigation:** deterministic policy checks, least-privilege tool access, explicit approval, and transport-level identity are used as controls. In production, document text should be treated as data rather than as instructions to the agent.

### Credential leakage

The demo contains no credentials. The REST adapter reads tokens from the environment.

**Impact:** leaked enterprise credentials can have critical security consequences.

**Mitigation:** use the company's secret manager, short-lived credentials, least privilege, audit logging, and never store tokens in source control.

## Demo data

The demo creates 1,000 supplier records and more than 1,000 related contracts, so the assistant is not being demonstrated against a tiny toy database.

Run `python generate\_demo\_data.py` to generate the data.

The resulting SQLite demo data can then be inspected through the MCP tools.

## Automated testing

This repository contains a dependency-free test suite covering the business layer and MCP wiring.

The final suite currently reports:

* 454 tests
* 454 passed
* 0 failures

The tests cover:

* required-field validation;
* supported-currency checks;
* duplicate supplier detection;
* partner and contract lookup;
* contract termination safety;
* state-machine misuse cases;
* risk-threshold cases;
* case ID determinism;
* audit logging;
* query-injection-style inputs;
* input limits;
* unknown-record handling;
* REST adapter configuration;
* MCP tool registration;
* MCP tool docstrings and callable wiring;
* approval enforcement.

Run the suite with:

`python -m unittest discover -s tests -p "test\_\*.py" -v`

## Real MCP runtime verification

The official MCP Python SDK is not bundled into the repository's source tree. Install it in the project's virtual environment:

`pip install "mcp\[cli]"`

The official SDK currently has a stable 2.x line, requires Python 3.10+, and provides the `mcp` CLI for development. Then run the runtime verifier:

`python verify\_mcp\_runtime.py`

The verifier uses the official SDK's in-memory `Client(mcp)` testing path to:

1. connect to the actual MCP server object;
2. list the available tools;
3. verify that every expected tool exists;
4. call a real tool through the MCP protocol;
5. list the policy resource;
6. read the policy resource.

The SDK documents this in-memory server and client testing mode as a way to exercise the real MCP protocol without starting a network port. See the [official testing guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/get-started/testing.md).

For the interactive development demo, the SDK also provides:

`mcp dev contract\_ops\_mcp\\mcp\_server\\server.py`

This launches the MCP Inspector. See the [official first-steps guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/get-started/first-steps.md).

## Production deployment shape

For local development, stdio is the simplest transport.

For a deployed service, use Streamable HTTP behind the company's normal gateway and identity system. The current SDK documentation describes Streamable HTTP as the transport to use for deployed servers. [MCP run documentation](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/index.md)

A realistic production setup would look like this:

Employee or AI host → MCP client → Corporate API gateway → MCP server → ERP, contract management, document, and approval systems → Audit and observability.

The production adapters would connect the MCP server to systems such as SAP or Oracle, Ariba or another contract platform, and ServiceNow or a similar approval platform.

The MCP server should remain stateless where practical, with authentication and authorization handled by the organization's identity layer. The 2026-07-28 MCP specification is designed around stateless HTTP requests, which makes ordinary load balancing easier for deployed servers.

Production authorization should use the organization's identity layer. The model must never be allowed to invent a reviewer identity or escalate its own permissions.

## What is mocked

The prototype intentionally mocks the vendor systems.

It does not connect to SAP, ServiceNow, SharePoint, or Docusign because no company credentials, approved endpoints, or production schemas were provided.

The adapter interfaces form the integration boundary. That means the mock implementations can later be replaced with real adapters without changing the MCP tool contract.

For example, these mock components:

* `MockPartnerDirectory`
* `MockContractSystem`
* `MockDocumentStore`
* `MockWorkflowSystem`
* `MockSignatureProvider`

can be replaced by integrations such as:

* SAP S/4HANA
* SAP Ariba
* ServiceNow
* SharePoint
* Docusign

## What a real rollout would add

Before connecting the prototype to production, the remaining work would include:

1. Map the canonical data model to the company's real APIs.
2. Replace mock adapters with approved integrations.
3. Put the MCP server behind the organization's identity and API gateway.
4. Derive user and approver identity from authentication rather than tool arguments.
5. Move policy configuration into a controlled configuration store.
6. Add production database storage and migrations.
7. Implement downstream idempotency and reconciliation.
8. Add monitoring, alerting, and tracing.
9. Add retry and circuit-breaker behavior appropriate to each vendor API.
10. Perform security, privacy, and compliance review.
11. Run a shadow-mode pilot before enabling writes.
12. Enable writes only after process-owner approval.

## Scope and evidence boundary

The task data supports the presence of recurring supplier, business-partner, and contract procedures. It does not expose every field, API, approval rule, or decision used by the real organization.

The business logic is therefore configurable, and any additional workflow assumptions are stated as assumptions rather than presented as facts about the company. The purpose of the prototype is to demonstrate how a fragmented multi-system process could be turned into a governed, AI-accessible service, not to claim that the synthetic policy is the organization's real policy.

