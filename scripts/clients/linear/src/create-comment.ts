#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("create-comment")
  .description("Create a comment on a Linear issue")
  .requiredOption("--issue-id <id>", "Issue identifier")
  .requiredOption("--body <body>", "Comment body")
  .parse();

const options = program.opts();

/**
 * Create a comment on a Linear issue using CLI-provided options and emit a structured response.
 *
 * Attempts to create a comment using `options.issueId` and `options.body`. On success emits a success
 * response containing `id`, `body`, `createdAt`, `issueId`, and `user` (an object with `id`, `name`,
 * and `email`, or `null` if unavailable). On failure emits an error response with code
 * `CREATE_COMMENT_FAILED` and an explanatory message.
 */
async function main() {
  try {
    const client = getLinearClient();

    const commentPayload = await client.createComment({
      issueId: options.issueId,
      body: options.body,
    });

    const comment = await commentPayload.comment;

    if (!comment) {
      respond(error("CREATE_COMMENT_FAILED", "Failed to create comment"));
    }

    const user = await comment.user;

    respond(
      success({
        id: comment.id,
        body: comment.body,
        createdAt: comment.createdAt,
        issueId: options.issueId,
        user: user
          ? {
              id: user.id,
              name: user.name,
              email: user.email,
            }
          : null,
      })
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    respond(error("CREATE_COMMENT_FAILED", message));
  }
}

main();