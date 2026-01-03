iterative constraint filter

prd creates constraint tickets that point out areas that do not meet constraints
for every constraint, validate that the constraint is met within the artifact
if the constraint is not met then create a ticket
the ticket does not state how to meet the constraint or prescribe a solution
the ticket simply states that the constraint is not being met and where it is not being met

so for every constraint, review the system against constraint and then create a ticket if the constraint is not met

constraints include

rules
algorithms
structures
resources
etc


all constraints are indexed
contraints can referene constraints
constraints can also be applied globally (if they say so)
when validating a constraint, that constraint is validated against what uses it
the thing that uses it must be validated to exist FIRST and then that thing decomposed into
its constraints, each individually validated (this is how rules get validated)
so the algorithm is creating a topological sort on

discover rule
discover what uses rule
add to validate list (thing exists; rule applies to thing)

when we come across the actual thing it may have its own non-referenced elements, which would be additional constraints

things exists (should already be in); thing's own constraints; referenced constraints (previously added already)

in this way we don't have to attempt to decompose a thing. we compose the validations iteratively through discovery