# System Architecture: CONSTRAINTS


([=CON-LIB-08-001])
<!-- source: overview.md:9-9 -->
The interplay between these eight systems — seven libraries plus the TransactionValidator — is what makes the engine both powerful and treacherous to change, because a modification to one library's timing assumptions can cascade into reconciliation breaks, missed regulatory windows, or silent audit gaps. The full architecture is documented across the following files:
