# ReAct Orchestrator is all you need.

We share a **ReAct Orchestration methodology and Agent Harness Prompt** for building a **Custom Orchestrator in Joule Studio that integrates Non-SAP Application Agents with SAP Applications**.

The Orchestrator interprets business requests, delegates tasks to the appropriate agents and tools, and determines the next action based on returned evidence. This approach connects SAP and Non-SAP environments while incorporating enterprise permissions and approval policies.

### ■ Sales Play: Integrate Today, Prepare for SAP Native Orchestration

> **If you need to connect Non-SAP Application Agents with SAP Applications today, start with a Custom Orchestration Agent in Joule Studio.**
>
> Implement the integration you need within the SAP stack, and design for a phased transition that reuses existing agents and integration assets as SAP Native Orchestration support expands.

The Custom Orchestration Agent coordinates collaboration between SAP and Non-SAP agents and manages tool execution. Integration options such as A2A, MCP, and Integration Suite connect the underlying business processes.

By **separating orchestration, domain-specific agents, and system integrations**, customers can address current integration needs and prepare for future expansion or transition, depending on Native Orchestration support and compatibility.

### ■ Workflow

```text
                             User Request
                                  │
                                  ▼
                        Joule User Interface
                                  │
                                  ▼
                       SAP Managed Orchestrator ─── Lookup ───┐
                                  │                             │
                  ┌───────────────┴───────────────┐             ▼
                  ▼                               ▼   Agent Card Registry
      SAP Managed Agents              Custom Orchestration Agent  (Agent gateway)
                  │                         (Joule Studio)             ▲
                  │                               │                     │
                  ▼                               └──── Lookup ────────┘
          SAP Applications                         │
                                                  ▼
                                   Non-SAP Application Agent
                                      (Kyma or Joule Studio)
                                                  │
                                                  ▼
                                    Non-SAP Application
```

In the proposed architecture, the **SAP Managed Orchestrator and the Custom Orchestration Agent both consult the same Agent Card Registry** for agent discovery and metadata lookup. The SAP Managed Orchestrator receives requests from the Joule User Interface and delegates either to SAP Managed Agents or to the **Custom Orchestration Agent**. The Custom Orchestration Agent then delegates to Non-SAP Application Agents deployed on Kyma or built in Joule Studio. A2A supports agent-to-agent communication, while MCP and Integration Suite provide options for tool and system integration. A phased transition can be evaluated as SAP Native Orchestration support and compatibility evolve, with the aim of reusing existing agents and integration assets.

### ■ Example: New-Hire Onboarding

**User Request:**

> "Process onboarding for new hire John Smith."

```text
SAP Managed Orchestrator (Step Decomposition)
│
├── Step 1 (SAP): Register employee profile in SuccessFactors
│           → SAP Managed Agent (SuccessFactors)
│
├── Step 2 (SAP): Create IT equipment purchase request in SAP Ariba
│           → SAP Managed Agent (Ariba)
│
├── Step 3 (SAP): Set up payroll account
│           → SAP Managed Agent (SAP Payroll)
│
├── Step 4 (NON-SAP · Custom Extension Assistant): Provision accounts in Slack / GitHub / Jira
│           → Custom Extension Assistant (Non-SAP)
│                   ├── Slack Provisioning Agent
│                   ├── GitHub Provisioning Agent
│                   └── Jira Provisioning Agent
│
├── Step 5 (NON-SAP · Custom Extension Assistant): Enroll in mandatory training on the corporate LMS
│           → Custom Extension Assistant (Non-SAP)
│                   └── LMS Enrollment Agent (Workday Learning)
│
└── Step 6 (NON-SAP · Custom Extension Assistant): Send onboarding completion notification
            to the line manager through Slack
            → Custom Extension Assistant (Non-SAP)
                    └── Slack Notification Agent
```

This example shows how one business request can combine SAP-managed onboarding steps with Non-SAP extension agents. The SAP Managed Orchestrator decomposes the request; the Custom Extension Assistant coordinates the selected Non-SAP agents.

### ■ Agent Card Registry

The planned **Agent Card Registry** centralizes Agent Card management for registered SAP and Non-SAP agents, including agents deployed on Kyma or built in Joule Studio. Both orchestrators use this single registry as a common source of agent metadata for discovery and delegation.

- **Centralized Registration:** Manage agent identities, capabilities, endpoints, and authentication requirements in one registry
- **Shared Agent Discovery:** Allow both orchestrators to discover candidate agents and retrieve their Agent Cards from the same registry before delegation
- **Lifecycle and Governance:** Track Agent Card versions and manage which registered agents are available for orchestration

The Registry manages metadata; each orchestrator sends execution requests directly to the selected agent endpoint.

### ■ Shared Resources

- **ReAct Orchestration:** An agent execution methodology that repeats Reasoning → Action → Observation to determine the next action
- **Agent Harness Prompt:** A prompt defining agent roles, operating principles, permitted tool use, collaboration, and decision criteria
- **SAP BTP Implementation Guide:** Guidance for building a Custom Orchestrator using Joule Studio and SAP BTP services
- **Multi-Agent Demo:** A demonstration of Orchestrator → Team → Specialist requests, responses, and the final review outcome

### ■ SAP Solutions to Consider

- **Grounding:** Context grounded in enterprise documents and data
- **SAP AI Core / Generative AI Hub:** Model access, execution, and generative AI orchestration
- **SAP Kyma:** An execution and deployment environment for custom agents
- **Joule Studio – Agent:** Agent creation and tool integration
- **RPT – Decision:** Decision support based on predictive results

### ■ Future Extension Areas

- **Integration Suite and MCP:** Connections to SAP and Non-SAP systems and external tools
- **A2A-Based Agent Gateway:** Request and response routing between agents
- **SAP LeanIX AI Agent Hub:** Enterprise agent inventory management and governance

### ■ Recommended Customers

- Customers seeking to build a **Custom Orchestrator in Joule Studio that integrates Non-SAP Application Agents with SAP Applications**
- Customers seeking to coordinate agent collaboration and tool execution across SAP and Non-SAP environments
- Customers seeking to incorporate enterprise-specific decision criteria and approval policies into integrated business processes
- Customers seeking to address current integration needs while preparing for phased expansion or transition to SAP Native Orchestration
