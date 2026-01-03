need to identify tests that cover a file from the file using call graphs

unit
component
integration

unit is 1:1 mapping so this is filename matching

component and integration require call graphs from "each individual test" in the file

we can simplify this further between slow tests and fast tests

whenever we do a run we identify imports that cause tests to be slow

examples

pytorch
docker
httpx

we only run our call graph for slow tests in component/integration to limit runtime
we run 1:1 matching for unit tests
if a component test or integration test matches our file then we can include it with no call graph matching

given a list of files find tests that touch those files AND list which files which tests touch
given a list of tests and the files that they touch schedule them in a topological sort with parallelization for running
N workers will be debugging tests in parallel. if a test touches multiple files and those files in turn have tests then those files cannot be debugged by the multi-test until they have
first been debugged by the individual tests. This is the scheduling problem. Unit tests can all run in parallel. Component and integration
will require scheduling. We first do unit + component tests that don't overlap with unit + integration tests that don't overlap with component or unit
Then we do component tests with scheduling where there are overlaps and integration tests with scheduling where there are overlaps where integration is lower priority than component.