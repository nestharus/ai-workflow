Adapting Agents and Orchestrations for VS Code
Copilot Extension
This guide provides a comprehensive overview of how to convert general AI agents and orchestrations into
the format and workflow expected by the Visual Studio Code GitHub Copilot extension (Copilot Chat with
custom agents). We will cover the required file structures ( .agent.md , .prompt.md , AGENTS.md ), how
orchestrators manage workspaces and sub-agents, how command outputs are handled, and best practices
for making your agents functional within VS Code’s Copilot environment. Each section below addresses a
key aspect of this adaptation, with examples and tips for clarity.
File Structure and Formatting for Agent Profiles
To integrate with the Copilot extension, agents and orchestrations must be defined in specific Markdown
files with particular conventions:
.agent.md – Custom Agent Definition
Custom agents are defined in Markdown files with an .agent.md suffix. Each .agent.md file contains
YAML frontmatter at the top, followed by the agent’s prompt/instructions. The frontmatter specifies the
agent’s metadata and allowed capabilities, for example:
---
name: implementation-planner
description: Creates detailed implementation plans and technical specs in
markdown
tools: ["read", "search", "edit"]
target: vscode
model: GPT-4
---
In this snippet, name is the agent’s identifier, description explains its role, tools lists which tools the
agent can use (e.g. file read, search, edit, shell, etc.), target can specify the environment optimization
(e.g. vscode for local VS Code, or github-copilot for cloud agents), and model optionally fixes
which LLM to use . After the frontmatter, the body of the file is the prompt that defines the agent’s
behavior or persona (usually written in natural language guidelines). For example, an agent might be
instructed with a role like: “You are a technical planning specialist who analyzes requirements and breaks them
into tasks…” and so on, enumerating its duties and style. This content guides the AI’s behavior when the
agent runs.
1 2
1
Formatting rules: Ensure the frontmatter is enclosed by triple-dash --- lines and written in valid YAML.
Common properties include name , description , model , tools , and (if needed) handoffs or
argument-hint for advanced chaining. The VS Code extension will validate and even provide
autocomplete for custom agent files . After the YAML, the rest of the file is typically a set of
instructions or context that the agent will always consider. This can include lists, steps, or any text – it
essentially serves as the “prompt” for that agent every time it’s invoked.
.prompt.md – Orchestration Prompt/Workflow Definition
Orchestrations (multi-step workflows) are often defined or initiated via prompt files. A .prompt.md file
contains the detailed gameplan or initial instructions for an orchestrator agent. Think of it as the “brain” of a
multi-step command: it tells the AI how to break down and execute a complex task . In practice, this
file can outline the workflow an orchestrator should follow: validating inputs, asking the user clarifying
questions, deciding when to invoke sub-agents or tools, and what to do with the results.
For example, an orchestration prompt might include a sectioned plan:
# Orchestration: Update Project Dependencies
## Plan
1. **Analyze current dependencies:** Read `package.json` and `requirements.txt`.
2. **Check for updates:** Use the `search` tool or an API to find latest
   versions.
3. **Apply updates:** Propose changes to dependency files.
4. **Test project:** Run the test suite (`shell` command) and capture output.
5. **Summarize results:** If tests fail, log errors; if pass, confirm success.
## Instructions
- Start by reading the dependency files.
- If outdated libraries are found, prepare an update plan.
- Use a sub-agent for running tests to isolate that context.
- ...
  Such a .prompt.md guides the orchestrator through each step. It can be written as a markdown checklist
  or outline that the agent follows. In VS Code’s paradigm, this is analogous to the built-in Plan agent’s
  prompt, which breaks down a high-level request into a detailed implementation plan . The orchestrator
  agent will use this file as its script, ensuring it doesn’t try to solve everything in one go but proceeds step-
  by-step.
  Note: The Copilot extension may not require a .prompt.md file explicitly named as such – often the
  orchestrator’s logic can reside in the .agent.md itself or be triggered by a custom command. However,
  organizing the workflow in a separate prompt file can be useful for complex sequences. It keeps the agent’s
  role definition (.agent.md) separate from a particular task’s execution steps. If using this pattern, make sure
  the orchestrator agent knows to load or refer to the .prompt.md content (some implementations load it
  via a tool like read at runtime).
  3 4
  5
  6
  2
  AGENTS.md – Project-Wide AI Instructions
  The AGENTS.md file is a special Markdown file (usually placed at the root of your repository) that serves as
  a README for AI agents . It provides global context, conventions, and instructions that any AI agent
  should be aware of when working on your project. In other words, it’s a centralized guide for AI, covering
  things like coding style rules, environment setup, or high-level project architecture—information that a
  human developer might put in a README or contribution guide, but tailored for an AI’s consumption.
  Copilot and other AI coding agents will automatically look for AGENTS.md to gather additional context .
  For example, your AGENTS.md might include sections about coding standards, how to run the project,
  important architectural patterns, or persistent dos and don’ts for the AI. This file should be written in plain
  Markdown, organized into sections (like “Dev environment tips”, “Testing instructions”, “API guidelines”, etc.)
  that an agent can scan. By structuring AGENTS.md with clear headings and bullet points, you make it
  easier for the AI to find relevant details.
  Important: Keep AGENTS.md focused and up-to-date. If it becomes too large (hundreds of lines), consider
  using an approach to compose it from smaller fragments as your project grows . The goal is to avoid
  overloading the agent with irrelevant context and to prevent the file from becoming stale. Think of it as a
  living document: whenever workflows or best practices change, update AGENTS.md accordingly (just as
  you would update documentation for human developers). This ensures all agents (orchestrators and sub-
  agents alike) always have the correct high-level guidance when operating on your repository.
  Isolated Workspaces for Orchestrations ( .tmp/UUID_name )
  When you run an orchestration (a multi-step agent session) in VS Code, the system will create an isolated
  workspace for that session. In practice, the Copilot extension uses a hidden folder (commonly named
  .tmp ) in your project to contain temporary files and context for each agent session. Each orchestrator
  execution gets its own subdirectory under .tmp , often named with a unique UUID or timestamp plus an
  identifier for the orchestration. For example, if you start an agent session to implement a new feature called
  “LoginFlow”, you might see a directory like:
  .tmp/ae3f9c7a-LoginFlow/
  This folder acts as a sandboxed environment for the orchestrator and any sub-agents it spawns. By having
  separate workspaces, multiple agents or runs won’t step on each other’s toes – their intermediate files and
  outputs stay isolated.
  What’s inside the workspace? The orchestrator will use this directory to store any transient data: for
  instance, command outputs (logs, test results), files generated on the fly, or even summarized context. It’s
  essentially the agent’s scratch pad. The main project files remain untouched unless the agent explicitly
  writes to them (e.g., editing code), and any heavy computations or file manipulations can be done in the
  temp space first.
  Generating the workspace: Normally, the extension creates the .tmp subfolder automatically when you
  initiate the agent. However, you can also set it up manually for testing or custom orchestrations: 1. Create
  7
  7
  8 9
  3
  the .tmp directory in your repository root if it doesn’t exist, and add it to your .gitignore (to avoid
  committing ephemeral data). 2. Create a subfolder named with a GUID or unique name for your session.
  Using a UUID ensures uniqueness; appending an orchestration name helps identify its purpose. 3. Prepare
  context files: If your orchestration needs certain inputs, you can copy or generate them into this folder. For
  example, if a sub-agent should only see a specific subset of files, place those files here. Otherwise, the
  agent can still read from the main workspace as needed using tools. 4. Point the orchestrator to this
  workspace: When you configure your custom agent/orchestrator, ensure it uses the new folder for its
  operations. In VS Code, this is handled behind the scenes, but if scripting manually, you might run the agent
  with its working directory set to .tmp/<id>_name .
  By structuring orchestrator runs in unique directories, you prevent clutter and make debugging easier – you
  can inspect the files in .tmp/... to see what the agent did or produced during the session. After
  completion, these can be cleaned up if not needed (the extension might do some cleanup or keep recent
  sessions around; you can delete old ones safely).
  Capturing Command Output in Files and Agent Consumption
  Within an orchestration, agents will often need to run external commands or tools (for example, compiling
  code, running tests, linters, etc.). The VS Code Copilot agent framework allows agents to execute terminal
  commands through tools (like a shell tool) – but the output from those commands must be captured
  and fed back to the AI in a controlled way. The common pattern is to pipe command outputs to files in
  the agent’s workspace, then have the agent read or summarize those files, instead of dumping long outputs
  directly into the chat.
  Why use files for output? Managing output via files prevents overwhelming the AI’s context window with
  raw logs and ensures important information persists beyond the immediate step. For example, if tests
  produce 500 lines of output, the orchestrator can store that in a test_output.txt within the .tmp
  workspace, then instruct the agent to open or parse that file (possibly summarizing it). This way, the agent
  only incorporates the essential parts of the output into its reasoning, and the full details remain available
  on disk if needed for reference.
  Mechanism: When an agent with the appropriate tool permission needs to run a command, it will either
  directly invoke the command via the Copilot tools interface or prompt the orchestrator to do so. In VS
  Code’s local agents, a tool like shell can execute a command and return its stdout/stderr. The
  orchestrator should then write those results to a file (or the tool might do so automatically). For instance,
  your orchestrator might internally do something akin to:
- Run tests with `npm test`
- Save the console output to `results.log`
- If tests fail, read `results.log` and find error messages.
  The agent will execute the npm test via shell, the output gets captured into results.log in the
  session workspace, and then the agent uses a read tool to ingest the contents of results.log for
  analysis.
  4
  Agent consumption of output: After the output file is prepared, the orchestrator can prompt the agent to
  read it. In Copilot’s environment, this might be as simple as the agent saying something like “Reading test
  results…” and using the file-reading capability. Some agents explicitly call out the file, e.g.,
  #file:results.log in the prompt to attach it, or the agent’s logic knows to open that file. The key is
  that the agent’s subsequent decisions (fixing a bug, for example) are based on the content of that file.
  For example, consider an agent trying to fix a failing test. The workflow might be: 1. Agent runs tests: The
  agent triggers pytest or npm test via the shell tool. 2. Capture output: The orchestrator pipes the
  output to .tmp/<id>/test_output.txt . 3. Analyze output: The agent then reads test_output.txt
  to find the failure reason (e.g., an assertion error and stack trace). 4. Plan next action: Based on the error,
  the agent decides how to fix the code, then proceeds to edit files.
  This kind of end-to-end autonomy – run, gather feedback, adjust – is exactly what agents in VS Code are
  designed to do . By using files as the interface between “running code” and “reasoning about code,” we
  ensure the agent has a persistent, referable record of what happened. It also limits how much data we feed
  directly into the prompt (we can choose to summarize logs or only focus on the key lines, rather than
  sending everything).
  Tip: Organize output files logically in the workspace. You might create subfolders like logs/ or
  outputs/ under the session directory for different types of results. Name files clearly (e.g.
  build_errors.txt , db_migration.log ) so both you and the agent can easily keep track of them. The
  orchestrator can maintain a small index or simply use consistent naming so that if the agent needs to refer
  to previous outputs, it can find them (for instance, “Open the logs/test_output.txt file to see details”).
  This practice helps in long sessions where multiple commands are run.
  Splitting Tasks into Steps and Maintaining a TODO List
  A core responsibility of an orchestrator agent is to break down complex tasks into manageable steps.
  Rather than trying to solve a large problem in one giant prompt (which can exhaust the context window and
  confuse the AI), the orchestrator should plan a sequence of steps and execute them one by one. This
  resembles how the new Copilot Plan agent works by first asking clarifying questions and generating an
  implementation plan . In custom orchestrations, you want a similar step-by-step approach, often
  maintaining a "to-do list" of remaining steps.
  Planning the steps: Typically, the orchestrator (or the agent developer) will outline the steps needed. This
  can be done dynamically (the agent itself comes up with a plan and lists steps) or statically (the
  .prompt.md already lists the steps as in the earlier example). Either way, the agent should be aware of
  what the sub-tasks are. It might present the list in a markdown checklist or numbered list in its output for
  transparency. For example, an orchestrator might say: “Here’s the plan: 1) Gather requirements, 2) Generate
  code, 3) Run tests, 4) Review results.”
  10
  6
  5
  Often, the first step is to gather context required for later steps. For instance, an orchestrator
  implementing a feature might first read relevant files (configs, existing modules, documentation) before
  writing any new code. As an illustration, a workflow could start like this (from a real orchestrator prompt):
  Step 1: Background Information Collection – “Read the latest specification file and user feedback
  relevant to this feature.” The agent is instructed to open certain files in the repository (using the
  read tool) and confirm that information is collected . It ensures prerequisites are met (if files
  are missing, the agent will warn or adjust the plan). Only after confirming the context is gathered
  does it proceed.
  Step 2: Execution of sub-tasks – These could be coding tasks, analysis, or calling sub-agents (more
  on that below). Each step should ideally end with some result saved (code changes, output files, or a
  summary) before moving on.
  Step 3: Verification – e.g., run tests as a step, capture output.
  Step 4: Wrap up – finalize changes, maybe commit or inform the user of results.
  Maintaining a TODO list: The orchestrator should keep track of which steps are done and which remain. A
  simple way is to use a checklist in a markdown file (or even just in its own memory/state). For example, the
  orchestrator could maintain a file tasks.md in the session workspace:
# TODO
- [x] Gather initial requirements and context
- [ ] Update the code for new feature X
- [ ] Run tests and analyze results
- [ ] Document the changes in README
  As the agent completes a task, it could mark it done ( [x] ) or remove it from the list. This file can act as the
  source of truth for remaining steps. The agent can refer back to it to decide what to do next, especially
  after a long sequence where it might have summarized or forgotten earlier context. Storing the plan
  externally is important because AI agents have limited memory – if the conversation gets lengthy, earlier
  messages might get summarized or omitted. By having the authoritative TODO list on disk, the agent can
  always reload it to see what’s left.
  Avoiding context loss: Large multi-step processes can run the risk of the agent losing track of goals or past
  steps due to context window limits (this is sometimes called “context confusion” as more and more is in play
  ). To mitigate this, orchestrators should summarize completed steps and drop detailed context that’s no
  longer needed, while keeping the high-level plan accessible. One strategy is: after finishing a step, write a
  brief summary of it to a progress.md or log file, then free up the conversation by clearing or summarizing
  that portion. The remaining steps still live in the TODO file. This way, even if parts of the discussion are
  pruned or summarized by the Copilot system, the agent can explicitly reopen TODO.md and
  progress.md to recall what’s been done and what’s next.
  •
  11
  •
  •
  •
  12
  6
  In practice, subagents (subtasks) help manage context, as the VS Code subagent feature demonstrates
  (spawning a separate context so that a deep dive doesn’t pollute the main conversation) . But even
  within a single agent, writing down future tasks is a form of manual context management. It ensures the
  orchestrator doesn’t “forget” steps simply because the conversation got too long or because it needed to
  summarize. Always store the source of truth for ongoing work in the workspace (either as files listing tasks,
  or as code comments, etc., that the agent can parse).
  To illustrate: Suppose our orchestrator is building a new module and has 5 tasks. It completes 3 tasks, but
  the conversation is getting long, and Copilot’s adaptive summarization might trim older parts. The agent
  would still have a TODO file showing the 2 remaining tasks. It might also have an interim result file from
  step 3. So at step 4, if it’s unsure, it can explicitly read the TODO file to see what’s next. This pattern keeps
  the agent oriented and resilient to memory limitations.
  Nested Orchestrations: Calling Sub-Agents and Workspace
  Switching
  Sometimes an orchestrator needs to delegate a subtask to another agent (or another orchestration). This
  could be because the subtask is complex or different enough to warrant a specialized approach – for
  example, doing research, performing an in-depth analysis, or simply to avoid cluttering the main agent’s
  context with a lot of intermediate detail. In the Copilot extension, the orchestrator can launch subagents
  (also known as sub-ordinators or nested agents) that run independently and then return a result to the
  main agent .
  How sub-agents are invoked: In VS Code’s Copilot Chat, this is often done via a tool or handoff. The recent
  versions introduce a #runSubagent tool in prompts, which the main agent can call to spawn a subagent
  with a given prompt or role . If you include a custom agent as a tool (for example, listing "tools":
  ["custom-agent"] in frontmatter or using the handoffs property to chain agents ), the main agent
  can effectively invoke another agent definition. From a user perspective, you might see the chat UI indicate
  that a subagent was started. Under the hood, the system likely creates a new .tmp workspace for the
  subagent (just like the main orchestrator had) or at least a clean context, and executes the subagent’s
  .agent.md logic there.
  For a manual orchestration design, the pattern would be: 1. Prepare subagent input: The main
  orchestrator writes any necessary state or instructions for the sub-agent into a file accessible to the sub-
  agent’s workspace. This might include the specific question or data to process. For example, “Subtask:
  summarize the findings from files A, B, C” could be written to .tmp/subagent_X/input.md . 2. Spawn
  the subagent: The orchestrator (or the system) initiates the subagent agent, pointing it to its isolated
  workspace (e.g., .tmp/subagent_X/ ). In VS Code, using #runSubagent with a reference (like
  #file:input.md for context) essentially does this . At this moment, the main agent is paused or
  awaits the result. 3. Subagent execution: The subagent runs independently, with its own context window.
  It might read the input.md , do whatever work (web research, heavy computation, etc., depending on its
  tools and permissions), and then produce an output. The final answer or result is typically written to a file or
  returned as the subagent’s last message. 4. Return and merge: When the subagent finishes, the main
  orchestrator resumes. The result is made available to the main agent – in VS Code, only the final result of the
  subagent is injected into the main agent’s context . This could happen by the extension automatically
  passing the subagent’s answer as a message, or by the main agent reading a output file that the subagent
  13
  14 15
  13
  16
  13
  15
  7
  produced. The key point is that the main agent regains control and now has new information (the
  subagent’s output) to incorporate, without having seen the subagent’s entire internal conversation.
  This keeps the main context clean.
  State management with .pop : The question mentions “switching workspaces with .pop ”. This
  suggests a mechanism to return from a subagent context back to the parent (like unwinding a call stack). If
  you have scripted your own orchestration controller, you might implement a special command or file
  (perhaps named .pop ) that signals the system to close the sub-workspace and pop back up. In VS Code’s
  built-in system, this is handled implicitly when the subagent finishes (the agent tool call ends). But if
  designing manually, you’d do something like: after the subagent writes its results, the main orchestrator
  reads that and then deletes or ignores a flag file that was indicating it was in sub-mode.
  Restoring previous state and action tracking: When the main orchestrator comes back, it needs to
  restore its state as it was before the sub-call, plus incorporate the subagent’s outcome. This means any
  variables or progress it had (perhaps stored in its state files or memory) should be reloaded. If you had
  paused the to-do list, now you mark that sub-task as done and maybe attach the result. Often,
  orchestrators will tag the returned data so they remember where it came from. For example, if subagent
  “Researcher” returned a summary, the orchestrator might write in its state.md :
  **Researcher_summary:** *(content from the researcher agent's findings)*
  Using such tags (like a prefix or heading) lets the main agent later reference that information easily by
  name. It’s a way of saying: “I have this piece of state from that sub-process, and I know what it is.” Tools and
  frameworks differ in how they do this tagging – some might use YAML structures, others simple markdown
  annotations. The idea is to log what action was taken and what result came back. This is crucial for complex
  orchestrations where you might call multiple subagents and need to keep their outputs distinct. By tracking
  actions, if something goes wrong or if a later step needs to know “Did we already do X? What was the
  outcome?”, the orchestrator can check these state notes.
  To clarify with an example, imagine an orchestrator with steps: (1) gather requirements, (2) do research via
  subagent, (3) implement code, (4) test. When step 2 (research) is done by a subagent, the orchestrator
  receives the summary. It could store:
  [Subagent:Research] Summary of authentication strategies: ... (text) ...
  Then, in step 3, when implementing, it can refer to this summary (the main agent might literally copy it into
  its prompt or just use it as needed). Because it was tagged and saved, even if the conversation memory was
  trimmed, the agent can open the state file to recall what the research found.
  In VS Code’s terms, subagents are supported for local sessions and the system manages context handoff
  automatically . You just need to ensure your custom agent definitions take advantage of this (for
  instance, by using tools: ["search", "read", "shell", "custom-agent"] and instructing when
  to use a custom-agent or runSubagent ). The extension’s handoff feature can also facilitate structured
  transitions – for example, the Plan agent can hand off to the implementation agent once the plan is
  14 17
  8
  approved . In custom agents, you can define handoffs in YAML to say "after completion, pass control to
  X agent" . This is another way to chain orchestrations without manually coding the push/pop logic – the
  platform will manage invoking the next agent with the relevant context (often context is passed via an
  intermediate file or prompt that includes the necessary state).
  Returning State to the Orchestrator and Using Tags
  When a subagent or even a simple tool action is completed, the orchestrator needs to capture the state/
  result and integrate it. We’ve touched on this in the subagent scenario above. More generally, any agent
  (sub or main) that produces output which needs to be persisted should return that output in a structured way for
  the orchestrator to handle.
  For example, if an agent finishes a code analysis and produces a report, the orchestrator should take that
  report and perhaps save it to a file or embed it in the ongoing conversation with clear delimiters. Tagging it
  with an identifier (like [AnalysisReport] at the start) can help the orchestrator refer to it later or make
  decisions. This is analogous to how an AI might label different pieces of information internally; here we
  make it explicit in the files.
  State files: You can designate a file (or multiple files) in the workspace to accumulate state. Some designs
  use a single state.yaml or state.json for machine-readable accumulation of results, while others
  just append to a markdown log. If using markdown, headings or bold labels can serve as tags. If using
  JSON/YAML, keys can be the tags. For instance, a YAML state file might end up like:
  subagent_research_summary: "Authentication X is recommended because...
  (truncated)"
  tests_passed: true
  errors: []
  The orchestrator agent can be instructed to update and read this state as needed. In VS Code’s agent
  system, while there isn’t an out-of-the-box “state file” concept, nothing stops your agent from reading and
  writing to files as a means of memory. Doing so is a clever workaround to the context limit.
  Tagging conventions: Choose a consistent way to label the state contributions. For example: - Prefix by
  agent or step name (e.g. Researcher: or Step3Result: ). - Use markdown quotes or code fences if the
  content is large or structured (so the agent doesn’t confuse it with its own instructions). - Document in your
  orchestrator’s prompt how these tags should be interpreted. You can explicitly tell the agent: “I will store
  important results in state.md under headings. Always check state.md for relevant info at the start of a
  new step.”
  This way, the agent knows to incorporate that file’s content proactively. It’s similar to how an agent might
  refer to AGENTS.md for global rules – here it refers to the session state for dynamic data.
  Example scenario: The orchestrator is fixing a bug. Step 1, it ran the app and got an error log. It saves the
  error in state as [RuntimeError]: ... message ... . Step 2, it did a code analysis with a subagent,
  which found root cause and suggested a fix. It saves that as [Analysis]: ... recommendation ... .
  16
  16
  9
  Now in step 3 (implement fix), the orchestrator can check those state entries: - It sees [RuntimeError]
  and ensures the fix addresses that error. - It sees [Analysis] which guides how to fix. It then makes the
  code change. After that, it might update state with [FixApplied]: true or record what commit was
  made.
  While this might seem verbose, it significantly reduces confusion, especially in long sessions. It mirrors
  good software practice (logging and state tracking) but for AI reasoning.
  Best Practices for Command Execution in Orchestrations
  Designing orchestrations that execute commands requires careful consideration to keep the AI on track and
  the development environment safe. Here are some best practices and patterns:
  Separate "thinking" from "doing": The AI (agent) should decide what needs to be done, but when
  it comes to performing actual system changes or heavy operations, hand that off to a deterministic
  process. In the Copilot extension context, this means leveraging tools or scripts. For example, if the
  agent needs to format code or run a database migration, have it call a script or use a controlled tool
  rather than generating raw shell commands inline. This principle is emphasized in frameworks like
  NioPD, where each command agent uses a shell script for filesystem operations, isolating the AI’s
  reasoning from side-effects . By doing so, you avoid the AI accidentally issuing destructive
  commands—it can only invoke predefined actions that you’ve allowed.
  Use tools provided by Copilot VS Code: When you specify tools in an .agent.md , include
  those that match your needs. Common tools for local agents are:
  shell – to run terminal commands.
  edit – to edit files (Copilot can apply edits directly to code).
  read or search – to read file contents or search within the workspace.
  custom-agent – to invoke other custom agents (subagents).
  websearch or other custom tools – if available and needed (e.g., for research tasks).
  Limit the tools to what’s necessary for the agent’s role . If the agent’s job is purely analysis, perhaps it
  only needs read and search . If it will be modifying code, give it edit (and maybe restrict it from
  dangerous shell commands unless required). By tailoring tools, you enforce the scope of what the agent
  can do.
  Validate before executing: In your orchestrator prompt instructions, include checks and
  confirmations before running big commands. For instance, an agent should verify that a build script
  exists before running it, or confirm with the user if it’s about to do something potentially risky (like
  deleting data). This can be done in the “Preflight” section of your workflow. In the earlier example
  from NioPD’s PRD drafting command, the prompt had a Preflight Checklist to validate inputs and state
  before proceeding to later steps . Emulate that pattern: list conditions and have the agent stop or
  ask for guidance if something is amiss.
  Keep commands idempotent and safe: Agents might run commands multiple times (for example,
  re-running tests until they pass). Ensure the commands you allow won’t produce irrecoverable
  •
  18
  •
  •
  •
  •
  •
  •
  1
  •
  19
  •
  10
  changes if run repeatedly. Prefer read-only or build/test commands in orchestrations. For
  deployments or destructive operations, it’s best to require explicit human approval or use a very
  controlled agent.
  Pipe and parse outputs: As discussed, always capture outputs to files. Then guide the agent to
  parse those outputs. You can include parsing instructions in the agent’s prompt. For example: “After
  running the tests, open the test_output.txt file and look for lines containing 'FAIL' or 'ERROR'.
  Summarize those lines for the user.” This level of guidance helps the agent focus on what's important.
  It prevents the agent from getting lost in lengthy logs. Remember, the agent doesn't natively know
  what's critical in a log file unless told – so provide heuristics or patterns to look for (exceptions, stack
  traces, etc.).
  Iterate and self-correct: A powerful aspect of agents is the ability to iterate. Encourage the
  orchestrator to use a loop of plan → act → check. If the check (e.g., test results) indicates failure, the
  agent should refine its approach and try again, rather than giving up or completing with an error. In
  fact, Copilot agents are designed to self-correct on failed tests or errors . In your custom
  agent, you can script this behavior: e.g., “If tests failed, analyze the failure and go back to fix the
  code, then run tests again. Repeat until tests pass or a stopping criterion is reached.” This makes the
  agent robust and closer to an autonomous developer that doesn’t stop at the first obstacle.
  Use templated outputs for reports or summaries: If the orchestrator’s goal is to produce a report
  (say a code review or a plan), use a consistent template. You can either include this in the prompt
  (like a markdown outline the agent should fill in) or store a template in a file and have the agent load
  it. This yields more structured and predictable outputs. For instance, you might have a report-
  template.md with sections for “Summary, Issues Found, Recommendations” and instruct the agent
  to populate it. Structured outputs are easier for humans to read and for any post-processing you
  might do.
  Logging and transparency: Have the orchestrator echo what it’s doing at each step (either in the
  chat or in a log file). This is useful for you to follow along and also for the agent to keep track. For
  example, the agent might output in the chat: “ Step 1 complete: gathered context. Proceeding to
  Step 2: updating code.” These acknowledgments can be derived from your plan/todo list. They not
  only inform the user but also serve as breadcrumbs in the conversation history.
  Stay within the extension’s limits: The Copilot extension (especially in local VS Code) can have rate
  limits or token limits. Very long interactions might get cut off. Be mindful of this by not letting any
  single step’s output balloon unnecessarily. That means if a command output is huge, prefer to
  summarize it before feeding it back. Or if a subagent’s result is very large, perhaps it should be
  distilled. Copilot also sometimes will explicitly summarize or truncate content if it’s too large. By
  controlling this flow yourself (with purposeful summarization), you maintain quality of information.
  By following these practices, you leverage the Copilot extension’s capabilities fully – using it to run code,
  fetch context, and even apply edits – while keeping the AI’s reasoning process structured and monitorable.
  Essentially, the AI becomes a cooperative pair programmer executing a well-defined gameplan, rather than
  an unpredictable black box.
  •
  •
  20 21
  •
  •
  •
  11
  Read-Only Sub-Agents and Orchestrator Mediation
  In multi-agent setups, it’s often wise to designate sub-agents as read-only or limited in scope, and let the
  main orchestrator be the one that makes changes or runs risky operations. The rationale is to keep
  specialized agents focused on analysis or planning, and centralize decision-making for state changes in the
  orchestrator. This pattern aligns with the idea of a “code reviewer” or “tester” agent that only observes and
  reports, while a main “implementer” agent applies fixes .
  Read-only subagents: A read-only subagent might be one that you configure with no edit or shell
  tools – perhaps only read , search , and maybe the ability to call other informational services. For
  example, a “Security Auditor” agent could be allowed to scan code and produce a report, but not allowed to
  modify code. In the agent profile, you simply omit any write-capable tools. The agent then knows its role is
  advisory. GitHub’s documentation example describes a custom agent that “would only have read-only access
  to the codebase and use specific documentation as context… The outcome would be a detailed report” . This is
  exactly the concept: the agent can read and analyze, but any code changes have to be made by either the
  user or another agent.
  Applying this to orchestrations, you might have subagents like: - Researcher – reads docs or searches the
  web, returns findings. - Analyzer – inspects code or data, returns an analysis. - Reviewer – reviews code
  changes, returns feedback. - Tester – runs tests (this one might need to run commands, so maybe not
  purely read-only, but it doesn’t write code, it just executes and reports).
  Meanwhile, the main orchestrator agent (or a dedicated “Implementer” agent) is the one that actually edits
  files or makes commits based on those inputs.
  Passing execution requests to orchestrator: How does a read-only subagent request an action be taken?
  Since it cannot directly run a tool it doesn’t have, the subagent must communicate its intent. Usually, this is
  done through its output or via a structured protocol between agents: - The subagent could output a
  statement like: “I recommend running the test suite now.” The orchestrator, monitoring subagent outputs, will
  see this and carry it out using its own tools. - In more strictly coded systems, the subagent might write a
  specific token or command to a file that the orchestrator watches. For instance, the subagent might write
  <<<REQUEST:shell:npm test>>> in its result, which the orchestrator parser recognizes as “run npm
  test ”. The orchestrator would then execute it and possibly feed the results back to the subagent. - If using
  the Copilot extension’s built-in capabilities, a subagent could also indirectly trigger an action by using a
  handoff: for example, finishing its job and handing off to a different agent that has the needed tool. But
  assuming a simpler case, we handle it at the orchestrator level.
  The important point is that the orchestrator remains in control of actual side-effects. The subagent may
  suggest or even implicitly require an action (like “there’s an error, we need to fix it”), but the orchestrator
  decides when and how to execute that fix. This is safer and often more effective, because the orchestrator
  can aggregate multiple inputs before acting.
  Example: The main agent asks a subagent “TestRunner” to run tests (imagine TestRunner is a subagent that
  only runs tests and reports results, no code writing). TestRunner has the shell tool to actually run tests,
  because that’s its job. It does so and returns a summary like “2 tests failed: XYZ test – AssertionError, ABC test –
  TypeError”. Now the orchestrator uses another subagent “Debugger” or its own logic to figure out the cause
  22
  22
  12
  of those failures. The Debugger subagent (read-only) says “It looks like function foo() returns null which
  causes the TypeError. We should fix foo() .”. The orchestrator takes this advice and then itself (or via an
  implementer agent) performs the code edit. Here, TestRunner and Debugger were both limited in scope
  (one only ran tests, one only read code and diagnosed) and neither directly changed the code. The
  orchestrator coordinated and ultimately executed the code change. This separation of concerns can reduce
  mistakes and make the overall system’s behavior easier to understand and trust.
  In VS Code’s environment, you as the orchestrator designer get to choose these roles. If you create multiple
  custom agents for sub-tasks, give them minimal permissions. For instance, a “PlanningAgent” might not
  need any shell access – just the ability to read files and output a plan. If part of that plan requires
  executing something, the plan will be handed off to another agent or back to the user. This principle not
  only follows the principle of least privilege (good for safety) but also encourages clear modular design of
  your AI workflow.
  Finally, ensure the orchestrator is programmed to catch sub-agent outputs and react appropriately. If a
  subagent’s result indicates it couldn’t complete its job (maybe it lacked info), the orchestrator should decide
  whether to provide more info or fail gracefully. If the subagent requests an action (explicitly or implicitly),
  the orchestrator should log that and execute it if it agrees. Essentially, the orchestrator plays the role of a
  supervisor who watches the tools and subordinates and makes the final calls.
  By implementing the structures and practices above, you can convert general agents and orchestrations
  into a format that is fully compatible with the GitHub Copilot VS Code extension and its custom agents
  system. In summary, define your agents with .agent.md profiles (plus any supporting prompt files), use
  the .tmp workspace scheme to isolate session data, break tasks into steps with persistent TODO tracking,
  delegate with subagents when needed (using the extension’s tools like #runSubagent to maintain
  context boundaries), and always feed outputs back into the agent’s workflow via files and structured state.
  These techniques align with how Copilot’s own advanced agents operate – enabling complex, multi-step
  coding tasks to be handled reliably by AI . With clear headers, well-organized instructions, and
  careful tool use, your adapted agents will not only function in VS Code but excel at assisting development in
  a controllable, transparent way.
  Sources:
  Visual Studio Code & Copilot Docs – Custom Agents and Subagents
  NioPD AI Orchestration Example – Command/Agent Structure and Best Practices
  AGENTS.md Specification – Purpose and Usage as AI README
  GitHub Copilot Release Notes – Agent workflow and handoff features
  GitHub Docs – Custom Agent Profile Example (Tools and Structure)
  VS Code Copilot Blog – Context Management with Subagents (runSubagent tool)
  Example Orchestrator Prompt (NioPD) – Stepwise Workflow and File Operations
  VS Code Copilot Overview – Agents handling multi-step tasks (testing, fixing, etc.)
  Creating custom agents - GitHub Docs
  https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/create-custom-agents
  October 2025 (version 1.106)
  https://code.visualstudio.com/updates/v1_106
  GitHub - iflow-ai/NioPD: NioPD (Nio Product Director) Is Your Virtual Product Expert Team on
  Claude Code, freeing you up to focus on product strategy and users.
  https://github.com/iflow-ai/NioPD
  A Unified Experience for all Coding Agents
  https://code.visualstudio.com/blogs/2025/11/03/unified-agent-experience
  GitHub - agentsmd/agents.md: AGENTS.md — a simple, open format for guiding coding agents
  https://github.com/agentsmd/agents.md
  Stop Fighting Your AGENTS.md File: A Better Way to Scale AI Agent Documentation - DEV Community
  https://dev.to/ivawzh/stop-fighting-your-agentsmd-file-a-better-way-to-scale-ai-agent-documentation-51n4
  Using agents in Visual Studio Code
  https://code.visualstudio.com/docs/copilot/agents/overview
  draft-prd.md
  https://github.com/iflow-ai/NioPD/blob/b526ad6b4430e40fb386f85e446cdaa1754ecc4c/core/commands/niopd/draft-prd.md
 