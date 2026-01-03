### Recursive Signal Sieve Algorithm

This approach treats the review bot's attention as a finite resource. By removing files with "loud" signals (bugs/improvements found), you reduce noise, allowing the bot to detect "weak" signals in the remaining files during parallel execution.

#### Phase 1: Scan & Partition

1. **Review:** Run CodeRabbit on the current working set.
2. **Check:**
* If no suggestions found: Mark all files in set as **CLEAN**. Exit.
* If suggestions found: Proceed to Partition.


3. **Partition:**
* **Loud Set:** Files containing one or more suggestions.
* **Quiet Set:** Files containing zero suggestions.



#### Phase 2: Parallel Descent

*Spawn two independent processes.*

**Process A: Mitigation (Handling the Loud Set)**

1. **Action:** Agent applies changes to **Loud Set** based on reviews.
2. **Commit:** Create a new commit with changes.
3. **Squash:** Squash the new commit into the 2nd commit (the working feature commit).
4. **Recurse:** Restart Phase 1 using only the **Loud Set**.

**Process B: Discovery (Probing the Quiet Set)**

1. **Context Shift:** Isolate the **Quiet Set**. The "Loud" files are removed from the context window entirely.
2. **Recurse:** Restart Phase 1 using only the **Quiet Set**.
* *Logic:* With strong signals removed, CodeRabbit may now identify improvements in these files that were previously ranked too low to mention.



#### Phase 3: Convergence

1. **Exclusion:** As soon as any branch marks a file as **CLEAN** (returns 0 issues), add it to the **Global Exclude List**.
2. **Termination:** The algorithm stops when 100% of files are in the Exclude List.

### Benefits of this Topology

* **Signal Unmasking:** Prevents critical bugs from hiding nitpicks. The "Quiet" files get a dedicated pass immediately, rather than waiting for the "Loud" files to be fixed.
* **Token Efficiency:** You stop sending the "Loud" files to the "Discovery" thread, and you stop sending the "Quiet" files to the "Mitigation" thread.
* **History Hygiene:** The "Squash to 2nd commit" rule ensures that despite the recursive branching, the final git history appears as a single, polished commit on top of the base.

### Next Step

Would you like me to generate the pseudocode for the `Partition` function that splits the CodeRabbit JSON response into these two file sets?