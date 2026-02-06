# Spec Decomposition and Execution Algorithm

I am designing an algorithm to refine and execute extremely large specs. I need you to do research and
improve upon the algorithm to ensure that we will never drop any details from the specs as we refine it
and that we will come up with the best outcome possible. You cannot assume that any text within a spec
follows a set pattern. You can only assume that there exists many different patterns across specs that,
through inference, can be identified contextually and locally within 1 specific spec file. These patterns
are not uniform. They cannot be extracted by regex or any type of script. They can be recognized as a
pattern based on the order within them. As such, you cannot rely on anything hardcoding, word
recognition, header recognition, or any other kind of specific pattern recognition to recognize these
patterns. The only thing you can rely on is that they have some kind of order to them that forms a
pattern. The best thing to recognize general patterns is an LLM. GLM is very good at summarizing and
selecting what is important. Opus is very good at recognizing patterns. ChatGPT is very good at tracking
details. I'm looking for script commands with algorithms / workflows that can be run (they execute
agents), agents that can be run (underlying agents), and agent commands that can be run (what the user
executes). You don't need to specify the specific syntax for each thing, nor should you. I have an agent
execution framework. You just need to know that agents can be run and that scripts can be executed as
commands. You are covering the algorithms, workflows, and agents in order to facilitate this process.
You are going to be uncovering mistakes in my existing algorithm (below) and improving upon/fixing those
mistakes. We don't need logging. We don't need extreme visibility. We don't need robust retries. This is
a prototype. We just need to get it working reasonably well with a way to track if we dropped details or
not and investigate those dropped details. We can even just use LLM as a judge with ChatGPT 5.2 XHigh or
even ChatGPT 5.2 Pro with a script that stitches together necessary context (everything is labeled). We
can brute force this with extremely powerful models to make sure that details were captured in
implementations. We don't need isolated workspaces. We will likely use ChatGPT 5.2 XHigh to really brute
force audits. GLM will write out code. Opus will likely do planning, while GLM finds evidence and
hook-in points. We'll be using File IO to communicate between these agents to reduce context pressure
and using IDs on files/folders and subfolders to ensure that things don't conflict with each other. We
need to be very aware that ChatGPT likes to wipe out changes with git checkout and git restore so need
to protect changes from ChatGPT.

Summarize the "what" is in each spec document. Not the details. Is an algorithm in there? Label it and
state what it is that it does (the intent of the algorithm). Various stores or components in there?
Summarize and state their intent. Will be using a GLM sub-agent per file. These will go into summaries
folder. Summaries will be annotated with the evidence used to contribute to them (which sections of the
file were summarized) (each section is labeled) ([FILEPATH::SECTION]),

For each summary identify high level concerns. The typical "libraries" underneath the summary. Describe
generally what each library is responsible for.,

Between libraries detect overlap. Throw overlap as a responsibility for one library or another or
create a new library to handle the overlap. Isolate all concerns. Show how libraries use each other.,

For each library x summary file pair (1 agent per pair), determine which summaries may potentially help
in creation of the library.,

This will break the spec out into isolated projects

Identify libraries that could have their own internal libraries and repeat the process until you have
no more candidates.

Now consolidate details between libraries. Rewrite, label. This will translate your input spec into a
bunch of libraries that are very isolated.

Next step, for each library refine specs. Continue refining specs to resolve all ambiguities. Then
continue to search for sub-libraries. Keep doing this until no ambiguities remain.

Next step, 1 agent proposes architectures that "could" work. It looks at the large libraries and
proposes large architectures to organize them. Each architecture is filled out by looking at the
underlying libraries and proposing additional architectural candidates and seeing how they fill out.
This is done all the way down, pruning bad candidates as it goes down. This is specifically looking at
architecture. How components communicate. How they are organized. This cares less about the tiny
details. Eventually there are several strong architectures. These architectures are analyzed for
tradeoffs between them to pick the most suitable for the system using a very powerful model. A final
architecture is chosen.

Next, the library functionalities are distributed across the architecture by reference.

Next, begin implementing functionality bottom-up. Select leaves that rely on as few things as possible.
There can be cycles. Cycles are implemented together. You are looking for the minimal number of edges
for each body of work. Each individual atomic unit is implemented by a single agent. The edges are
negotiated beforehand and then all agents run in parallel to execute against the negotiated edges.

## Edit: Continuous Spec Refinement

Continuous spec refinement should actually be done during implementation. After you identify general
libraries you then implement everything in parallel. You go as far as you can. No dependency analysis.
As you run into ambiguities agents will block.

This system is to decompose specs. I need you to find problems. It primarily relies on needle in the
haystack to extract things reliably. There are some areas where reliability may reduce. Relations, for
example, are vague. It likely needs to find entities within relations themselves (discovery) and then for
each entity identify new information. This can isolate facts that may apply to two entities and isolate
precise relations between entities.

In the zip archive you produce you only need to present the files that you edited.

Other agents may not do true needle in the haystack problems where you just try to find something about
something.

There could be edge cases where information is not extracted correctly. The system attempts to handle
all edge cases but you are going to try to find things that were not considered.

The system currently provides no way to use the spec. We have a spec-decomposer but we also likely need
a tagger (tagging entity ids; tagging facts) so that everything has a unique id. We need to deduplicate
information but still leave it readable. So we do have duplicate information but it shares the same tag.
When we edit information we edit everything with the same tag. This will also let us see a blast radius.

The information would need to be recomposed around entities in a usable format that has no risk of
dropping information. Any rewrite introduces risk. Moving information around with scripts is safe.

So we'd need a tagger in our CLI and we'd need a recomposer in our CLI. The recomposed files would be
the final minified implementable specs that we would use.

Alias-detector is highly vague and unreliable. A good way to do it would be during implementation. When
an agent starts implementing something and researching they can see that another system is already
fulfilling the role and figure it out. So this would be an important note to add for using the specs
(dealing with aliases).

Another important note to add when using the specs. We can't reliably detect dependencies. We just
implement whatever we can during implementation. When we can't go further, we know WHAT we need. We
investigate our specs to determine what provides what we need and we implement those things next, then
we continue with our original implementation. This is a stack approach. What gets tricky is that things
may rely on each other. We'd need a broken staging area where we can push up what we currently have. Then
other things can use what we have. So this isn't actually a stack.. more of a list of things we're
continuously working on. We'd need to say which IDs we completed from the spec and which IDs are
partial. We can't say how they are partial but we can provide the files where we implemented things for
those IDs for something else to pick them up.

So we continue to add dependencies as we iterate. When we stop building something we add things it needs
(though it doesn't know from where). We push into our target work area (where things are shared). We
figure out what provides those needs and push implementation on those things for those particular needs.
Where things can get dicey is when two things cyclically need each other. We can detect that though.

So what it sounds like is we need to actually implement agents and scripts to do implementation. For
worktrees or whatever we don't use those directly. We have a CLI to manage our versioning and it does
whatever it does. It could be jj. It could be git. We don't care. We just use that to abstract it out.
You can start it on git worktrees for simplicity.

Any area where you are taking a solution that I didn't specify (like using git) would need an abstraction
so that the solution can be changed.

So it does sound like we need an execute spec command. execute-spec would go until we can't do anything.
The spec may be underspecified. So we say "we need something" and we investigate and the spec doesn't
actually cover it. That would turn into a gap. We continue implementing until we can't go further and
only have gaps left. Those gaps at the end of execute-spec would be surfaced to the user so that they
can further refine the spec. They can just add new IDs to the spec and we'll be able to tell what is new
vs old because we are tracking what we implemented. However, they may edit IDs that we used. For every ID
we will need to store hashes so that we can detect edits. This can also protect the IDs from LLM edits
during execution or during decomposition. We can review these edits with a new agent using gpt-5.2-high.
We have glm, gpt-5.2-high, gpt-5.2-xhigh, claude-opus, minimax. Researching typically uses gpt 5.2 high
or xhigh. opus is typically used for orchestration and understanding patterns. minimax is typically used
for gruntwork. So we can take incoming IDs and use opus to figure out how they apply to our existing code
(planning) and use minimax to actually implement them. We can use gpt 5.2 high to review the
implementation against the IDs to ensure that we didn't drop anything. Even more clever, the implementor
(minimax) should populate a json file (in .tmp/ or somewhere) to tie each thing it wrote to a particular
ID. This will allow GPT to review the implementations against the evidence more directly. If an
implementation fails then that can be passed to opus to figure out a way to integrate and minimax can once
again do the grunt work.

## Edit: Prototype Driven Development

Prototype Driven Development (PDD)

What if building a prototype was the best way to plan code? Not writing a spec. Not coming up with
tickets and managing dependencies. Just building a prototype and then cleaning it up.

The trick is that you are building your plan and implementation in parallel at the same time. Plan as
little as you can get away with. Constant baby steps. If you try to specify everything ahead of time you
will just drop details and drift. You can add controls to detect drift and track details but now you are
making a really complicated system. Instead, work in phases. Each phase produces something messy. The
next phase cleans it up.

Phase 1: Build and Partial Testing

1. Research

2. Sparse planning

3. Create worktree

4. Implement everything in parallel on worktree grandchildren. No dependency tracking. Write small tests
   to validate small units of work.

5. Block on ambiguity or missing requirement, rebase parent to main, rebase grandchild to parent, merge
   grandchild to parent, return to step 1 to resolve ambiguity

6. Pass sparse specs + implementation to POWER model for alignment check. This also checks for reward
   hacking.

7. Return to step 1 for sparse patch

8. Create high level overview document for human review

9. Human skims the document or only the updates since last approval

10. Human references intent misalignment

11. Return to step 1 for intent realignment

12. Human approves

You'll end up with bad architecture and bad code but it will work.

Phase 2: QA

1. Create large QA evaluations against the approved high level document

2. Detect failures

3. Root cause analysis

4. Return to phase 1 step 1 to create patch

Phase 3: Architecture

1. Architecture proposals

2. Architecture analysis

3. Architecture choice across proposals (usually a hybrid)

4. Refactor

Phase 4: Code Quality

1. Code quality gate (N reviewers that each enforce different standards)

2. Refactor

3. Merge root worktree to main

You'll end up with spec documentation and a high signal overview document. Your team can review the
overview document.

Spec Format

The specs need to follow a very specific format.

1. Analysis Docs - various options and why things were chosen

2. Constraints - shared guiding principles like priorities

3. Overview - explanations of how things fit together and what things are. Prose.

4. Details - algorithms and shapes

All elements receive unique IDs. This format can be parsed and separates the noise from the raw details
while providing context to understand the raw details and how to expand upon them.

Worktree Hygiene

You want a dirty root worktree and a sibling clean worktree. As slices of work are completed, they are
extracted from the commits and pushed on to the clean worktree where tests can run and pass. Then the
dirty worktree is rebased on to the clean worktree. This avoids final big bang integration.

*edit*

Now I need a baseline score of just raw GLM model being handed a spec (the step 1 spec) and being told to
  implement it using sub-agents (agent runner using GLM). Compare raw GLM score to the overall workflow score.
  The general workflow also needs to be able to accept input from a user and request input from a user as it
  runs into ambiguities. So it shouldn't try to solve those ambiguities on its own. It should allow users to
  provide answers and then have it patch specs with those answers and update refinements and pass along to
  agents. Something like that.

  I'd like another test using raw Claude Code opus agent (no agent runner). It would use its normal task system
  and normal processes and implement using sub-agents.

  How many details were captured? When inputting a number is the output correct?.

  We're not running our evals. We're just running the spec raw as it is to compare our system against a model
  baselines.

  I'd like another one using ChatGPT 5.3 Codex XHigh on Codex.

  If the score is too high then we need to keep adding new details to the test to complicate the calculation.
  We need to quadruple the number of details in the calculation each time. The number of rules. We also need to
  complicate integration. Make it so "algorithms" need to actually be split up and integrated across multiple
  points of the system in order to properly use the rules. So introduce complex architectures (brownfield
  existing system). The algorithm needs to have COUNTLESS rules to integrate into a highly complex system where
  things are decomposed and non-obvious. Use things like event loops so that the code cannot be easily traced.
  Event loops, multi-threading, message pipelines, etc. Make things as difficult as possible. We only need 1
  end to end eval test for this and that same system can also be used on our individual eval tests instead of
  the multitude of systems that currently exist to really stress test them. We also need to introduce
  "unrelated connections" into the system. Algorithms that run when other algorithms run that don't actually
  contribute. Things like logging or notifications. So we'll end up with an event log that we need to check as
  well to make sure that all of our connections were hooked in correctly. These connections should be
  non-obvious. The architecture of the system should also be heavily obsfucated and dense so that it is
  difficult to understand. We need to work on this system for evaluation before we get baseline scores and we
  need to run this system through first raw GLM to break it, then Opus 4.6 to break it, then GPT 5.3 Codex
  XHigh to break it. Once we break a model we move on to the next model. We continue to increase complexity
  until we can break the model. We increase integration complexity until the model begins to miss integration
  points. We increase rule complexity until the model begins to drop rule details.

  The other note, for our SYSTEM evals, is that, as part of the algorithm, our input spec is going to be
  sparse. The agents WILL need to ask for decisions as they run into ambiguities. Our script needs to provide
  those decisions to guide the spec to where we eventually want it to go. For our raw evals we are passing in
  the complete extremely detailed spec in one go as one large file. This means that we likely need to update
  how we do our evals for our system so that it truly works on a sparse spec. We need a way for users to
  collect ambiguities (as a report; specified) and return responses to those ambiguities that then get
  integrated into the overall spec and passed on as answers to agents that asked questions. In --auto mode we
  run a research algorithm. agent flywheel website shows, as one of its tools, a research algorithm. We can
  utilize that research algorithm and run it on Opus, GPT, and GLM using firecrawl. GLM can determine if we
  find any value while Opus can keep things generally aligned while GPT continues to perform synthesis etc.
  Opus can also be used to extract "signals" for GLM to search for and summarize. Like Opus can say why
  something is relevant and then GLM can summarize details for further analysis and then GPT can synthesize
  individual details later.

  *edit*
  For code ingest with no associated plans, code can be viewed as architecture + algorithms. High density, but noisy due to the architecture. The algorithms would need to be isolated (architecture removed). The goal is to separate it back into clean, constraints, and overview folders. Ideally these folders are maintained and the specs operated upon in parallel to code. This is possible because of the dense algorithms (lack of prose). It's possible to detect which algorithms were transformed by editing the code if the original algorithms are maintained. Another option is to do two versions of the system in parallel. One version of raw algorithms (no architecture) and the other version with architecture. You trace architecture back to algorithms / architecture layer separately. This allows you to test your algorithms. So the "clean" folder can be actual code rather than algorithms and then "actual actual" code can be translations from raw algorithms to architecture.