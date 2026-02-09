# Event Infrastructure: DETAIL — ALGORITHM


([=ALG-LIB-05-001])
<!-- source: event_pipeline.md:3-3 -->
The EventPipeline is the nervous system of the settlement engine. It implements a pub/sub architecture where each event is published to a named topic and consumers subscribe to the topics they care about.


([=ALG-LIB-05-002])
<!-- source: event_pipeline.md:29-29 -->
Ordering is guaranteed within a topic partition, so consumers processing events from a single partition will always see them in the order they were produced; however, ordering across partitions is not guaranteed and consumers must tolerate out-of-order delivery when reading from multiple partitions. If a consumer fails to acknowledge an event within thirty seconds the pipeline retries delivery. The retry policy uses exponential backoff with a base of one second and a multiplier of four, producing intervals of 1s, 4s, and 16s for the first, second, and third attempts respectively. After the third failed attempt the event is moved to a dead-letter queue where it remains for ninety days before automatic purging.


([=ALG-LIB-05-003])
<!-- source: event_pipeline.md:31-31 -->
The pipeline also supports transactional publishing, meaning that a producer can publish events to multiple topics atomically; if any publication in the transaction fails, all publications in that transaction are rolled back. Event payloads are serialised as JSON and must not exceed 256 KB per message; oversized payloads are rejected at the producer side with a `PayloadTooLarge` error.
