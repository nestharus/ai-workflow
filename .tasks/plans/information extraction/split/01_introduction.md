## Introduction

Large unstructured text documents often contain repetitive and interdependent details, making
it hard to manage updates or ensure consistency. This project aims to create a system that **extracts all
unique, atomic facts** from a given document (or set of documents) and organizes them into a structured
knowledge base (a "detail index"). The system will deduplicate facts, resolve references, and record
contextual relationships, so that each piece of information is stored exactly once. This allows easier
reviewing, editing, and conflict checking, since updating a fact in one place will effectively update it
everywhere it was referenced in the original text. The solution focuses on **local execution** (no cloud
services) with simple, fast-starting tools, and it prioritizes **accuracy and completeness** (no loss of
information, where completeness is defined by derivability - sufficient base facts to derive all implications).
