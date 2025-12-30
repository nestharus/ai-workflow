---
description: Recursive counter that chains calls to itself, decrementing until zero
mode: subagent
model: openai/gpt-5.2-none
tools:
  task: true
---

You will receive a number. If that number is 0 then immediately return 0. If that number is not 0 then you will call the recurse sub-agent with your number minus 1. When the recurse sub-agent returns back to you, you will prepend your number to its numbers separated by a comma and a space -> <MY_NUMBER>, <THEIR_NUMBERS>.
