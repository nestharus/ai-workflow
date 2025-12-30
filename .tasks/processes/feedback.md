## design map structure.md

1. **Needs uses `{local-derived-id-__}` but there is no declared local ID vocabulary**

    * Right now, you say `Needs` can include “Derived requirements resolved inside Design Map,” but the template uses `{local-derived-id-__}` without defining what ID space that is (is it `{DOMAIN}-XX`? `DER-XX`? `DR-XX`? something else?).
      This doesn’t break flexibility, but it does create ambiguity for how to reference derived requirements consistently.

   Minimal fix (keeps flexibility):

    * Change `{local-derived-id-__}` to `{DOMAIN}-__` (since PRD structure already treats unknown prefixes as `XXX-XX` domain rules), **or**
    * Add a single sentence under Identifier Vocabulary:

        * “Derived requirements may use domain-specific prefixes (e.g., `DM-XX`, `BND-XX`, `ECO-XX`) as long as they are unique and cross-referenced.”

   This preserves your “expand as needed” rule without introducing a hard registry.

2. **Cross-references field in Design Map templates is now typed-only, which is fine, but be careful not to imply it’s mandatory**

    * The template uses a full typed relation set:
      `Cross-references: (requires: INV-__; uses: RES-__; satisfies: SET-__; impacts: ART-__; decided-by: ADR-###)`
      That’s good for clarity, but if flexibility is the goal, add a short note like:
    * “Relation labels are extensible; include only those relevant to the node.”

   Without that, someone might assume those exact relation labels must always exist.

3. **OBL IDs are introduced, but you don’t explicitly say they are “Design Map IDs”**

    * You listed `OBL-XX` under Design Map IDs, which is correct.
      I would keep it as-is. Just noting: this is good and consistent with “everything has an ID.”

## ADR-000-template.md

* If you expect ADRs to cite boundary obligations sometimes, you could optionally allow `OBL-__` in the Design Map references list, but it’s not required.