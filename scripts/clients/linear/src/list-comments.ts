#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("list-comments")
  .description("List comments on a Linear issue")
  .exitOverride()
  .requiredOption("--issue-id <id>", "Issue identifier");

try {
  program.parse();
} catch (err: unknown) {
  // Allow help and version to exit cleanly
  if (
    err &&
    typeof err === "object" &&
    "code" in err &&
    (err.code === "commander.helpDisplayed" || err.code === "commander.version")
  ) {
    process.exit(0);
  }
  // All other parse errors return structured JSON
  const message = err instanceof Error ? err.message : String(err);
  respond(error("INVALID_INPUT", message));
}

const options = program.opts();

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
