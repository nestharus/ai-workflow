### Additional Assumptions

During the design process, a few ambiguities were identified and addressed with assumptions: - **Choice of
Vector DB:** We assume using SQLite with its extension for vectors as it meets the local and simplicity
requirement. Alternatives (like a pure Python in-memory search or using an open-source vector DB such as
Chroma) were considered. SQLite was chosen for its lightweight nature and ease of integration into the dev
environment. This decision assumes the scale (number of facts) is manageable (hundreds or a few
thousand facts, which is likely for a 200-page document). If scale grew to millions of facts, a more specialized
solution might be needed, but that's beyond our current scope. - **Sub-Agent Prompt and Behavior:** The
exact prompting strategy for the two-phase extraction pipeline (Haiku 4.5 sub-agent 1 for detail
extraction, Haiku 4.5 sub-agent 2 for fact construction) is to be refined during implementation. The
sequential pipeline design allows the detail extraction sub-agent to focus on extracting raw content while the fact
construction sub-agent handles the more complex task of anchoring and triplet structure validation. The PRD assumes we can
get the sub-agents to output their respective artifacts (details, then facts) cleanly. In practice, it may require
iterative prompt tuning or even some post-processing of model output (like regex to split bullet points, etc.).
We also assume the models are reliable in not hallucinating facts that aren't in the text - we will need to
instruct them clearly to only extract given information. The explanation-driven reconstruction approach
provides a built-in verification mechanism: by attempting to re-explain the original text using extracted
facts, we can test whether the current understanding is sufficient. When reconstruction fails, the anchoring
operation attempts to find facts that explain the uncovered (unanchored) text. If anchoring succeeds
(uncovered text shrinks), the failure was due to missed facts. If anchoring fails after bounded attempts
(no reduction in unanchored text), this indicates structural comprehension failure - the system cannot
understand what the unanchored text means or belongs to. In this case, the system emits Clarification
Questions rather than inventing meaning - preserving alignment through honest admission of non-understanding. A larger reasoning model
is only invoked when strictly necessary (e.g., borderline dedup adjudication, fluff classification when
deterministic rules fail, or high-quality Clarification Question generation). If local models + deterministic
rules suffice, the reasoning model is not invoked. - **Atomic Fact Definition Edge Cases:** Some information might be arguable
whether it’s one fact or two. For example, "The device is compact and lightweight" – one could see this as
two facts ("device is compact", "device is lightweight") or as one combined characteristic. Our rule is to split
on "and", so we’d make it two. This should be fine, but we note that sometimes combined adjectives or lists
will increase fact count. This is acceptable as we prefer granularity. - **Context Link Representation:** The
format for storing links between contextual facts is not yet formalized. Links are stored as untyped
hypotheses; the system is not required to assign semantic types such as "prerequisite" or "is-a". It could
be as simple as a note in the fact text (like "Linked to Fact ID X") or a separate structure linking Fact IDs.
For now, we will likely add a column like linked_fact_ids for any fact that has related facts. The
graph of facts and links is assumed to be incomplete; incompleteness is surfaced only through
reconstruction failures and Clarification Questions. - **Contradiction Handling:** As stated, the
system currently does not resolve contradictions. It will happily store contradictory facts if the source document contains
them. We assume for now the source document is internally consistent, or if not, that highlighting contradictions will be
done later by analyzing the fact list. The main objective now is to gather facts and unify duplicates, not to
decide which conflicting fact is correct. A future extension could use logical checks or domain rules to flag
such issues. - **Integration with LLM for Use:** We expect the output to be used by an LLM for tasks like
question answering or updating the source document. We assume that the consumer LLM/tool can ingest either the CSV/
JSON or query the SQLite. For instance, a script could load all facts into a vector store in-memory and then
given a user query, find relevant facts and present them to the LLM. The details of that integration (like a
chatbot that uses this data) are outside this PRD's scope, but our output is designed to be general-purpose
for any such use case.
