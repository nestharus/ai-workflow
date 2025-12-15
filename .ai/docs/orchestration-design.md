Review the following paper for accuracy of claims per latest research and articles.


AI orchestration pipeline

Primary roles

1. Implementation


2. Drift Reviewer


3. Artifact Reviewer


4. Pipeline Oversight


5. Planner


6. Investigator


7. Researcher


8. Crawler


9. Orchestrator


10. Translator



The job of the implentor is simply to follow instructions. It must be powerful enough not to understand intent but to follow literal instructions.

The job of the drift reviewer is fact extraction and matching. The reviewer's job is to take two artifacts and compare them where one artifact is the spec of another. It is focused on capturing drift.

The job of the artifact reviewer is to enforce a domain of artifact rules on that artifact. It must deeply understand the artifact and its rules to recognize when they have been violated. These rules can be architectural, anotomical, contextual. The rules are highly flexible. These enforce best practices on produced artifacts.

Pipeline oversight ensures all agents in the pipeline are following the rules of the pipeline. These agents can investigate artifacts for trickery and other dubious behavior. There are clear patterns. Agents attempt to trick other agents by stating that a decision has been made to do something else instead. They can show this in their log output or embed it into the artifact. Enforcers look for these patterns. They also look at deviation receipts. All agents must state when they deviate. These are immediately flagged by other agents in the pipeline unless the deviation was justified. At that point only the enforcer can recognize it. If no output is given then other agents can recognize that the agent that did not produce output (a receipt) is acting strangely and flag the artifact as suspicious. Agents try to be lazy but they hold each other accountable to keep the pipeline accurate.

Next we have the planners. There are strategic planners and integration planners. Any type of operation can be planned. A dev plan. A test plan. Anything. Planning always goes to strategy and then to integration. Strategy planners work with humans to define the how. After that the rest is automated. Deviations are sent back to strategy planners to define a new strategy and try again. The human oversees the strategy planners to ensure that it is being produced the way they want. Strategies are shorter.

Investigators try to get an artifact working. If it works immediately the investigator lets it pass. If not it works to get it working. This is done in isolation on a copy of the artifact. The artifact is modified and the tests are modified until it works. It then reports why the artifact did not work. This goes back to strategy to determine if the plan must change and proceeds all the way down the pipeline. The artifacts cannot pass through until the investigator approves them.

Next is the researcher. They synthesize information. They deduplicate and organize. They must recognize when information is the same and compare information to each other.

Crawlers work on small pattern recognition. They work in large swarms to search for anything that might be related to the small topic they are trying to recognize. If you have a list of topics then you send out multiple waves of tiny crawlers. Crawls can be optimized with graphs, databases, vector stores, etc. They can absolutely brute force a crawl on unstructured text though.

The orchestrator routes the information along the pipeline. It recognizes outputs to decide what action to take next. Outputs may not be static. They could be semantic. Orchestration decisions could rely on an LLM or a script.

Translator takes raw human input and determines the intent. They organize the input and work with the human to understand precisely what the human wants. The goals. Even how those goals get done. They act as the layer between the product researcher, the strategy planner, and the human to determine what to do and how to do it. This is the direct interface. This really focuses on understanding intent and communicating that intent and then returning back results in a very easy to read and small format. They can also tell the human about the artifact that was produced so that the human can verify that they got what they wanted. They can also report to a human when things go awry and work with them to do something else. They can offload many ambiguous tasks and details. Humans typically like to focus on specific things. It is up to the translator to determine what is important to the human.

You have several types of orchestrations

Create    
Audit    
Repair    
Integrate    
Review    
Update
