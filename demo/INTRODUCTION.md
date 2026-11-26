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
             ┌────────────────┴────────────────┐
             ▼                                 ▼
  SAP Managed Orchestrator         Custom Orchestration Agent
                                         (Joule Studio)
             │                                 │
             ▼                      ┌──────────┴──────────┐
     SAP Managed Agents             ▼                     ▼
             │              SAP Application      Non-SAP Application
             ▼                  / Agent                 Agent
      SAP Applications              │                     │
                                    └──────────┬──────────┘
                                               ▼
                                  Consolidate Responses
                                       and Evidence
                                               │
                                               ▼
                                  Check Permissions and
                                      Approval Policies
```

The **Custom Orchestration path** connects SAP and Non-SAP environments through options such as A2A, MCP, and Integration Suite. A phased transition can be evaluated as SAP Native Orchestration support and compatibility evolve, with the aim of reusing existing agents and integration assets.

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
