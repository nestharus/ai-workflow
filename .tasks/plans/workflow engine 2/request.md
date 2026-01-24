referenced workflows

 .claude\commands\review-implementation.md

.claude\commands\update-pr.md



we need a new command. open-project .claude\commands. This creates a new workspace for a project where it can accept documentation

  about that project and tickets. The command creates the workspace BUT the agent stays active to manage that workspace.

  The user passes it information to populate the documents and tickets. From there the user can open a ticket-manager

  agent for that workspace. This agent will create a worktree based on the ticket name. The user will continue to pass

  tasks to implement the ticket. These tasks will be broken up into steps each time. These steps require context from

  prior steps. The tasks are contextually self-contained. The user passes in the COMPLETE task with all steps. We first

  break the task up into is steps with important information about prior steps. When an agent executes a step it runs

  git diffs to grab deltas from prior steps as it implements. These steps are executed in order. At the very end all of

  the commits from all of the steps are squashed to represent the "task". This does not yet squash tasks together. They

  are kept separate. Our implementation reviewer workflow is then executed with the worktree and our task plan (all of

  the steps) against our task commit. This means that we don't need to run our scoping agent. Our python script just

  continues to gather new commits from the latest task onwards.

  Once the task is complete we are back to the ticket manager. The user can pass in their own feedback for a task, which

  would run the update pr workflow.

  The user continues to add tasks until they close out the ticket by telling the ticket manager to close it. This will

  squash all commits on the worktree. It will then run a ticket review using the ticket items to make sure everything was captured. We use implementation reviewer workflow given ticket and the commit. Finally run .claude\commands\rebase.md workflow and then .claude\commands\merge.md

  workflow.

  Worktrees are opened based on the current checked out branch and are merged back to the checked out branch



our open-project command should really be project-manager



We can go to our project manager to get next tickets. It will give us the command to run to open the ticket (ticket manager) and what to do. It also knows the ticket ordering.



As part of ticketing we can schedule tickets to determine if some tickets can be run in parallel. So our next ticket can return multiple tickets.



The thing feeding information into all of this is Traycer Epic Plan Mode + Phases Plan Mode.



We actually need our project manager to run on its own worktree. Then we need the ticket managers to each run on worktrees based on the project manager's worktree.



We create a worktree evaluation. So we create another worktree where we squash all of the ticket commits into one big commit. This is so that we can see the final state isolated from other changes without needing to compute it.



We use that commit to run an implementation review against all of our plan documents.



Next we need to store our specifications and tickets for investigation and tie them to this 1 commit. We need to store this into linear as a project. It'd be the project description. We change its status to completed. There's a whole linear cli thing in scripts/ somewhere.



Now our rebase command no longer looks at linear tickets. It now looks at projects tied to commits. When it gets a conflict it does git blame to understand where the conflict came from and does research between the projects to determine what it is supposed to keep. If there are conflicts due to divergence then it must figure out dependencies between the two projects and broader consequences. One project may have refactored something while the other used the old version. If they are legitimately two different implementations then they cannot be merged together. There will be tradeoffs etc. It needs to surface this so that a new plan can be created to reconcile. Rebase needs to report all of its findings.



Rebase needs to make use of sub-agents to run the investigations. I think that ideally we store each document from the projects as resources on the project item in Linear rather than as a huge description. Then the description will have an index to show from high level to low level. This will allow investigators to drill down.