Breaking Up a Large Spec
I have a 300 kilobyte spec and I need to implement it. I used a traditional spec creation process rather than annotating upfront so I am in a real pickle. How do I break this monster up?

The Options That Don't Work
I could try to let AI do it on its own. That'll drop detail.

I could try annotating now. Information is mixed up. Entities may not align.

I could try duplicating things between docs by line IDs. I do not know if details doc B needs are missing because they are in doc A.

The Key Insight
LLMs are optimized for needle in a stack problems. You tell it to find something and it finds it with 99% accuracy. So ask it to find something.

The Extraction Process
Then replace what it found with an ID and put the actual information, with that ID, into another doc. Ask it again. Ask it to theorize based on evidence it finds. Remove the evidence. Keep asking until it says "don't know"

You've successfully extracted and isolated that information.

Do this across all of your documents for that particular item. It is now in its own little document.

Extracting Relations
Now use the isolated document to ask about what uses it or what relates to it. Remove and put id. Keep asking. Keep removing. This will remove all of the relations.

The IDs retain a lineage for contextual information.

Validating Completeness
The next step is to read everything you extracted and then read a doc and ask if AI learned anything new. This is needle in a hay stack problem again but now applied to contextual information. You can remove and add relations between context and your extracted information.

When you extract you need a form of the document with relations and context.