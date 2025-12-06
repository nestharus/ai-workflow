#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("list-comments")
  .description("List comments on a Linear issue")
  .requiredOption("--issue-id <id>", "Issue identifier")
  .parse();

const options = program.opts();

/**
 * Fetches comments for a Linear issue by ID, enriches each comment with its author data when available, and sends a structured response.
 *
 * On success, sends a success payload containing `issueId`, `issueIdentifier`, `comments` (each with `id`, `body`, `createdAt`, `updatedAt`, and optional `user` with `id`, `name`, `email`), and `totalCount`.  
 * If the issue cannot be found, sends an `ISSUE_NOT_FOUND` error. If an unexpected error occurs, sends a `LIST_COMMENTS_FAILED` error with the error message.
 */
async function main() {
  try {
    const client = getLinearClient();
    const issue = await client.issue(options.issueId);

    if (!issue) {
      respond(error("ISSUE_NOT_FOUND", `Issue ${options.issueId} not found`));
    }

    const commentsConnection = await issue.comments();
    const comments = await Promise.all(
      commentsConnection.nodes.map(async (comment) => {
        const user = await comment.user;
        return {
          id: comment.id,
          body: comment.body,
          createdAt: comment.createdAt,
          updatedAt: comment.updatedAt,
          user: user
            ? {
                id: user.id,
                name: user.name,
                email: user.email,
              }
            : null,
        };
      })
    );

    respond(
      success({
        issueId: issue.id,
        issueIdentifier: issue.identifier,
        comments,
        totalCount: comments.length,
      })
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    respond(error("LIST_COMMENTS_FAILED", message));
  }
}

main();