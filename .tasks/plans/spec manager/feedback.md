I have files in .tasks\plans\workflow engine 3 . They need to be reorganized. You'll scripts to move sections of
  lines
  around. Like line 5 to line 450. You'll be writing tools and the like to help you invoke this algorithm. You'll
  also be making use of sub-agents. We are going to end up with nested folders. Folders will be by vertical slices.
  We're also going to have an algorithm graph organized by algorithms with 0 incoming edges. These will have high
  level steps that are decomposed down the layers of our horizontal slicing across vertical slices at the highest
  layer of horizontal slice. So at the highest layer of horizontal slice, we have vertical slices. Our root
  algorithms will live up here. The steps will reference components that live in those vertical slices at that
  horizontal layer. Then we go down horizontal slices across our verticals. We have our next algorithms. We keep
  repeating this until we are at our leafs. The algorithms will be stored into horizontal slices rather than
  specifically components. Components live within a vertical slice but each component represents the first layer of
  horizontal slice within a vertical. The verticals would be the components. We always have horizontal slice, then
  vertical slices, then horizontal slice, then vertical slices. This means we do start with a horizontal slice. If
  algorithms live in horizontal slices then this first horizontal slices will be universal across everything. We then
  go verticals then go next horizontal slices etc. This highest order layer will be an algorithm of pure symbols.
  Algorithms can be composed of symbols as we go down. Symbols reference only algorithms at the next horizontal
  slices. So these aren't sliced into who owns what. These are an algorithmic graph view so that we can understand
  responsibility. This is our behavioral view.

  The following is our structural view (the actual horizontals and verticals). Our behavioral view lives in our
  structural view. We store behaviors via the above. We also have our data dependency view. Whenever something
  depends on data that has no edge leading to it (persisted) then that becomes a data dependency. So we have a graph
  that tracks data inputs/outputs to capture where data originates and where data goes. Data can be transformed but
  that transformation still contains signals from the original data. Those signals continue to move alongside the
  transformation. When we use data we may looking at a slice of that data. That slice contains signals. It may be ALL
  signals if the data gets smeared everywhere (an aggregation). It may be specific signals. So this is signal
  processing and tracking those signals. This lives in our algorithms. In stores of informatoin we need to understand
  signals going into those stores so that when we read those stores we can trace the signals back.

  Next we can detect across all of our structure when something is underspecified. Unknowns. Every step eventually
  maps down to a technical stack. Languages. Libraries. Etc. If something doesn't map then it is an unknown. We know
  something is unknown if a "step" within an algorithm never translates into a technical stack. If it always remains
  a symbol.

  The symbols in our graph map to multiple symbols. These parallel symbols are "potential candidates". This is how we
  map multiple vertical slices as potential candidates. When we eventually choose a candidate we choose a part of a
  horizontal slice within a vertical slice. So our graph is not "code". It is what "code" could be.

  Finally we have risks and tradeoffs. This is how we choose and prune candidates. We come to understand candidates
  as we discover their unknowns. Unknowns inform us of their pros/cons. The tradeoffs.

  data, memory, latency, speed, recovery, exfiltration, evidence breadth etc
  A particular risk is under-analyzing. We need to store parallel solutions. These turn into "candidates". We
  converge on candidates. Candidates have tradeoffs. We need to understand desired tradeoffs by component. If
  tradeoffs all align with desires it can be chosen "but" we must continue to find things that not just align but can
  score better. Then we end up with things that partially align but have higher scores in certain tradeoffs. This
  allows us to score important between tradeoffs. These ambiguities need to be resolved by user if there is nothing
  to help decide.
  We can better align tradeoffs also based on audience, where it is running, and how it is running. We need to drill
  into these questions. We also need to understand footprint, memory, and latency. We also need to understand things
  like concurrency, volume (n tasks), size (how big a task is). We need to continue to examine these invariants to
  help select appropriate tradeoffs. We also need to understand how the system is maintained. Is it pure AI? Nobody
  looks at code? Do humans write it? Quality checks? Which industry? What is the review process? This allows us to
  examine cost of ownership between maintenance, hardware, and user satisfaction. These in turn could have
  opportunity costs. Maintenance is time. Hardware is money. User satisfaction is reach/revenue. Timelines. Burn
  rates.

  Data

  1. The Origins (0-Edge Data)
  These are the Sources of Truth.

  Persisted Roots: Database records, File systems. (They exist before the process starts).

  External Roots: User Input, API Payloads. (They enter the system at runtime).

  The Rule: Every piece of data in your application MUST trace its "Signal" back to one of these roots. If you have
  data appearing out of nowhere (magic numbers, hardcoded strings), it is a "detached signal" and usually a code
  smell or configuration.

  2. The Transformations (Signal Preservation)
  You mentioned "Transformations contain signals." This is Provenance.

  Pass-Through: Function(A) -> Returns A. Signal is identical.

  Projection (Slicing): Function(User) -> Returns User.ID. The output contains a subset of the input signals.

  Aggregation (Smearing): Function(List<Prices>) -> Returns Total. The output contains "smeared" signals from all
  inputs. You cannot reconstruct the inputs, but the output depends on all of them.

  Structure

  The Flow Decomposition Algorithm
  Phase 1: Structural Topology (Identifying Origins)
  Objective: Distinguish "Roots" (Origins) from "Leaves" (Dependencies).

  Scan all files in .tasks\plans\workflow engine 3.

  Build a Directed Graph:

  Nodes = Flow Files / Use Cases.

  Edges = Explicit calls/references (e.g., Execute: OtherFlow).

  Identify Roots (Indegree = 0):

  Find nodes with zero incoming edges.

  Label: Originating Flow.

  Classify Roots:

  Input: Originating Flow metadata (Trigger type).

  If Trigger == User_Action OR Trigger == Critical_Event:

  Label: Core Flow.

  If Trigger == System_Maint OR Trigger == Aux_Event:

  Label: Auxiliary Flow.

  Identify Leaves:

  Find nodes referenced by multiple Roots or other flows.

  Label: Shared Sub-Flow.

  Phase 2: The "Cluster Hunt" (Data Gravity Analysis)
  Objective: Detect High Coupling/Low Cohesion blocks based on State Mutation.

  Tokenize the content of every Flow (Line 1 to N).

  Identify State Variables:

  Filter for variables that are written to (=, +=, set()).

  Ignore loop iterators or temp vars used only within < 5 lines.

  Classify Variable Lifecycle (The Brittleness Test):

  Type A: Persisted State: Variable maps to DB/Storage (exists across app restarts).

  Type B: Long-Lived Ephemeral: Variable exists across multiple logical steps/clusters but dies on restart. (High
  Brittleness/Risk).

  Type C: Pure Ephemeral: Variable created and destroyed within the local block (Projections).

  Detect Write Clusters (The "Heat Map"):

  Scan for "Proximity of Mutation": If Var A and Var B are Type A/B and are modified within 10 lines of each other
  repeatedly, they form a Cluster.

  Constraint Check: Do these lines contain complex logic (conditionals/loops) relying on this state?

  Yes: This is a Candidate for Extraction.

  Action:

  Extract the Cluster (e.g., Lines 5-450).

  Replace with Reference: Execute: [Cluster_Name].

  Phase 3: Semantic Classification (The DDD Sorter)
  Objective: Assign the Extracted Cluster to a Home.

  Input: A candidate cluster from Phase 2.

  The Noun Test (Entity Identification):

  Does the cluster strictly manage the lifecycle of a specific "Thing" (User, Order)?

  If Yes:

  Create Component: Components/[Noun]

  Create Service: Components/[Noun]/[Noun]Service

  Move Cluster Logic Here.

  The Reification Test (The Verb-to-Noun Strategy):

  Does the cluster manage a relationship or complex action between two entities (e.g., Invitation, Subscription)?

  If Yes:

  Reify the Verb: Invite -> Invitation.

  Create Component: Components/[New_Noun]

  Move Cluster Logic Here.

  The Shape Test (Pure Logic):

  Does the cluster rely only on inputs (no external state, no side effects on Type A/B vars)?

  If Yes:

  Classify as: Utility / Mapper / Algorithm.

  Move to Taxonomy Folder: Shared/Utilities.

  Phase 4: Physical Reorganization (Vertical Slicing)
  Objective: Finalize the folder structure.

  Create Root Folders:

  ./Core Flows/ (The Product)

  ./Auxiliary Flows/ (Maintenance)

  ./Components/ (The Vertical Slices - User, Guild, Invitation)

  ./Shared/ (The Horizontal Layers - Utils, Shapes)

  Migrate:

  Move Core Flows (Phase 1) to ./Core Flows.

  Move Auxiliary Flows (Phase 1) to ./Auxiliary Flows.

  Move Extracted Clusters (Phase 2/3) to their specific Components or Shared folders.






Flows detect how changing something impacts other things. If we change something then we can trace up to see all of the flows it is a part of. We can then look forwards/backwards along those flows to see any impact it may have. We can do this by flows and by data.


2 "entities" may actually refer to the same "entity". Invariants can live in entity A and other invariants can live in entity B. If the two entities are in fact the same thing (the same shape) they may be separated out by the invariants that they carry. We need to understand when we see two entities that appear to be the same thing if they are truly the same thing or if they are actuially t wo different things. If we treat them as two different things when they were meant to be the same then we end up dropping invariants from one of them and we lose detail. Entities can also overlap. The thing we REALLY need to be careful of is our invariants. How things must operate. Invariants are always part of the system. They inform how things will get composed downstream. Things inherit from the invariants of their parents. Or rather invariants apply to particular steps. So the unsolved problem here is not losing detail between "candidates" regarding invariants. If we store child invariants in a parent then we are leaking. Except, are we? We have invariants on steps. Those steps are symbols. So we have invariants at the horizontal slice and we govern how are steps must function. Our invariants start at low fidelity and then increase in fidelity as we go down. We still have to be weary of the 2 "entities" that are really the same thing problem. We also have to be weary of user introducing new invariants for new candidates and how those invariants should map to parents and other candidates. Should they map or not? We don't know. Except, we do know. Those invariants govern how a step is supposed to operate. If we govern how a step is supposed to operate (its guarantees etc) then those invariants map up to the parent. We then get conflicts between candidate invariants and parent invariants. A candidate cannot fulfill all invariants. This is how we get tradeoffs! We have higher order invariants that can inform of us which tradeoffs to ultimately make if we cannot fulfill all invariants. So this means that 2 entities with 2 different set of invariants actually form the shape of invariants what we expect that class of entity to have. We lose nothing. We just end up with tradeoffs.

1. The Resolution: Invariant-Based Identity
You asked: "If we see two entities that appear to be the same thing... are they actually two different things?"

The Answer: Identity is defined by the Union of Invariants, not just the Data Shape.

Case A: Contextual Projections (The "Facets")

Entity A (Registration Context): Shape {email, password}. Invariant: email must be unique.

Entity B (Billing Context): Shape {email, credit_card}. Invariant: email must be verified.

Conclusion: These are The Same Entity.

Why: The invariants are orthogonal (they don't conflict). You can combine them into a single "Master User" definition without breaking logic.

Action: In your architecture, these are two Vertical Slices (Registration, Billing) operating on the same Identity.

Case B: The Candidate Conflict (The "Tradeoff")

Entity A (Candidate 1 - Cache): Shape {data}. Invariant: Low Latency (<10ms). Weak Consistency.

Entity B (Candidate 2 - DB): Shape {data}. Invariant: High Latency (100ms). Strong Consistency.

Conclusion: These are Different Implementations of the same Symbol.

Why: The invariants conflict. You cannot be both Weakly and Strongly consistent at the same time.

Action: This is where your Tradeoff Engine wakes up.


Shutterstock
Explore
2. The Mechanics: Bubbling Up Invariants
You worried about "leaking" invariants. You are actually describing Constraint Propagation, which is desirable.

The Parent (The Symbol): Defines Requirements (Must-Have Invariants).

Parent says: "I need a StoreUser step. Requirement: Must not lose data (Durability)."

The Child (The Candidate): Defines Capabilities (Provided Invariants).

Candidate 1 (In-Memory): "I provide Speed. I violate Durability."

Candidate 2 (Postgres): "I provide Durability. I violate Speed."

The Result:

The mapping of Child Invariants to Parent Requirements reveals the Tradeoff.

You don't "lose" the detail; you explicitly bubble the Violation up to the Parent.

3. The Final Algorithm Refinement
We can now patch the "Tradeoff" section of your algorithm with this logic.

Phase 5: The Invariant Solver (Tradeoff Analysis)

Extract Invariants:

For every Step/Entity, tag its "Musts" (e.g., @Invariant: Unique, @Invariant: ThreadSafe).

Detect "Same vs. Different":

Compare invariants of similar entities.

No Conflict: Merge them. (It's the same entity seen from two angles).

Conflict: Flag them as Mutually Exclusive Candidates.

Score Candidates:

Compare Candidate Invariants vs. Parent Symbol Requirements.

Match: Perfect Candidate.

Mismatch: The difference is the Risk.

Example: Parent wants Speed. Candidate provides Safety.

Tradeoff: "We gain Safety, but we lose Speed."





we can try just different strategies to try and find what we are looking for.

grep (try a bunch of different keywords)

we can look at top level verticals and have a list of candidates in priority to explore (search)

one useful thing we have is our top level algorithms. We can see SYSTEM RESPONSIBILLITIES from these algorithms. We can map what we got to a responsibility. If it doesn't match any of the responsibilities then this is likely brand new. This can be a tiny piece of a subsystem so we don't necessarily know which responsibility it maps to. So this doesn't quite work. This could be changing a low low level things that is used across many responsibilities to something else, so grep wouldn't work either. So we need to ask, which responsibility is this trying to fulfill? What might use that responsibility? So what we need to do is annotate our steps with responsibilities that they fulfill. THEN we can search for responsibilities.



A statement may not given us enough evidence to understand a responsibility. So we can gather statements to grow our evidence to better understand responsibilities. This would happen when it doesn't map to any existing responsibility and we don't have enough in our system to understand how it interacts. We need to understand more about what it is trying to do. We need to understand the responsibilities it is trying to fulfill.

We don't annotate components. We annotate steps. Steps in algorithms. Those are what we annotate. We can annotate steps with many responsibilities.

I do see an issue though. Algorithms can reference algorithms from anywhere. Not just children. This will still be fine.


STEP 1:

First move lines around. You use scripts to
  cut lines directly. I don't want you summarizing and rewriting. You need to get the precise lines and
  organize them as evidence. You can understand entities within these lines and do an index that relates
  entities back to evidence. You're never rewriting/summarizing here. You do that as little as possible
  because we do not want to drop any details. Your evidence will be multple invariants and evidence can
  point to multiple entities. So you are sort of creating an .. evidence graph. You never rewrite the source
  material but you do state which entities the source material is talking about. When you then look at an
  entity to understand invariants you can get a slice of all of the source material that discusses the
  entity. Some things ar erelated to the "system" entity. You'll end up with lots of entities. Flows also
  serve as evidence for entities. Everything is evidence of some kind.