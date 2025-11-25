# Ticket and PR URL Handling

Users can initiate workflows by providing PR or ticket URLs to the orchestrator. The
system automates the process of fetching details and routing work to appropriate agents.

## Workflow Steps

1. **User Submission**: User POSTs a URL to the orchestrator.

2. **GitHub Agent**: Orchestrator invokes the specialized GitHub Agent to fetch details
   using MCP. This retrieves PR diffs, issue descriptions, labels, and other metadata.

3. **Automatic Routing**: Based on the content (e.g., labels, file paths), the orchestrator
   routes the ticket to the appropriate domain and role. For example, UI-related changes
   route to UI domain agents.

4. **Claiming**: For new tickets, the orchestrator broadcasts availability, and agents
   claim tickets on a first-come-first-served basis via the ticket manager.

## Claiming Mechanism

The ticket manager (`app/services/ticket_manager.py`) implements first-come-first-served
claiming. When a ticket is available:

* The orchestrator broadcasts the ticket to eligible agents
* The first agent to respond claims the ticket
* The orchestrator assigns the ticket and begins the workflow
