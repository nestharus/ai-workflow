each step within an orchestration is a tool that runs agents in a particular way
orchestrations follow workflows (start with a workflow) that can be modified
when you input arguments you go into an inference layer that configures an orchestration for you
it may just create the standard default orchestration
it may moodify the orchestration or even add additional extra steps
orchestrations can be modified to be loose (an AI runs the steps) or strict (steps run the AI)
when an orchestration is loose steps cannot run AI BUT steps can use state machines to communicate to the orchestrator to run
a particular step (like an ai) or proceed to another step

Example
- I need you to run this workflow and QA it

this would run it in loose where an AI runs the steps to understand problems and attempt to fix them

This enables users to pass in input that doesn't quite match up with the expected arguments. AI can configure the workflow
to run with the user's needs. The user may even say "I need you to use this workflow to understand how to get worktrees going so you can lint these files"
the user can even reference other workflows in a workflow. This enables great flexibility in composition while enabling
cheap standard workflow execution when the standard is enough.

even in strict mode, exceptions can be caught by an AI (strict with QA -> adapt to loose mode)
there can be escape hatches to exit the current orchestration and enter a new one (configure new orchestration; continue from here; skip this step; etc)
this means that we never really need loose orchestrations. we can run strict and reconfigure.

we need an initial inference layer when executing an orchestration to determine if we are running standard
or there's something strange happening that we aren't expecting. we can use a cheap local model to do this reasoning
like ministral 3B and then pass it on to a more capable model to figure out what exactly to do.


in general software, SaaS, etc, the exception handler can route to the agent, which can route to investigation etc
the agent can also work to repair the process in place. it can write tools to route whenever exceptions are caught for this
bug to get requests through. the idea here is that unless there is a literal outtage or keys are missing in an integration
that the agent will find some way to complete a request while a proper solution is being crafted and will route requests through
the tool (things will be a bit slower) until the fix is in.
a cheaper model can be used to classify the bug against a tool that exists
a more expensive model and a swarm can be used for investigation
bugs will be aggregated together as well for additional data points
information surrounding the bug (current state of the system) can also be gathered as part of investigation (readonly)

this technique can be applied to current orchestrations
orchestrations MUST log what they have done (steps, inputs, and outputs) without leaking secrets
this is for task history
this means that we never need a QA agent around an orchestration. QA is built right into the orchestration
when something breaks it is automatically captured and fixes are worked on along with immediate tools to patch things through
this means that all orchestrations can fundamentally run through python or static code as the entrypoint
we never have to use a model as the entrypoint