This actually can be changed.



We do not need a list of responsibilities.



Responsibilities are themselves algorithms.



Allow me to elaborate. Algorithms are composed of algorithms.



Algorithms all have contracts

You have classifications of algorithms, meaning algorithms can appear in multiple places. Why would you want this? Algorithms are adapted and integrated into whatever is using it. How do we prevent duplication? Capability. This allows us to actually decompose the internals of algorithms by examining internal capabilities and responsibilities.



A capability is an outcome

A responsibility is a role

Any particular algorithm can define its own responsibilities as it decomposes itself into inline components.

Like any contract, a violation depends on what is available within the executing environment.



Algorithms, even inline algorithms, can continue to be decomposed into smaller algorithms until they are irreducible (down to the instruction level). How does this help us? I am not sure yet.



We can work on a hierarchical level of responsibilities. This means that we can also use our metrics, risks, etc as we look at our algorithm. However, algorithms that provide the same capabilities and can fulfill the same responsibilities can have COMPLETELY DIFFERENT shapes. This is across the entire information system. How can we analyze these shapes to recognize patterns without getting lost in tiny details? We can look at runtime complexities of each algorithm to identify bottlenecks? computational complexity of each step? The overall shape can be O(n^2) and we can identify, mathematically, why it is O(n^2) by the composition of O(n) components. How does this allow us to find new shapes though? We have the components. We have the intent. We know what the shape is trying to do. We know the complexity. Now what? We can't necessarily optimize from what we have.



This is going into a more fundamental problem across the system. Across the components themselves, because the components themselves compose a large algorithm and a more correct solution can have, as we have proven here (bubble sort vs quicksort), a completely different shape. We can understand the shape of what we have, but can this help us discover a new shape? It can help us match the shape we identified against existing shapes to replace the shape, but can it help us actually come up with a new shape? We mentioned rearranging to produce new shapes to satisfy a constraint problem, but how does that scale? We have proven, without a doubt, that the ENTIRE shape can change.



If we look at an algorithm it does have its own internal little components that fulfill responsibilities. It is its own tiny little ecosystem. If we look at bubble sort vs quicksort, the shapes are completely different. When we look at large systems, they actually describe algorithms across many components. No matter how much we optimize individual components, the overall algorithm can still be wrong (we may need entirely different components).



If we can optimize small algorithms (bubble sort to quick sort), then can we optimize big algorithms by the same techniques? If we look at the components of a quick sort vs a bubble sort, we can also look at the components of a large-scale algorithm to swap out to different components. To identify large structures, the large algorithms, and then detail out the underlying components all the way down.



We don't know what our algorithm is when we have a problem. Our existing recomposition methods work to grow out an algorithm. However, recomposition reduces complexity of AN EXISTING algorithm. We still need to be able to analyze that existing algorithm as complexity is reduced and we need to be able to analyze at many different layers. Can we actually do this and can we reconfigure into new shapes in the same way we can on the individual algorithm?