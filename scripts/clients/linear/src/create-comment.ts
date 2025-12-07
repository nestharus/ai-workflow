#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

interface CreateCommentOptions {
  issueId: string;
  body: string;
}

const program = new Command();

program
  .name("create-comment")
  .description("Create a comment on a Linear issue")
  .exitOverride()
  .requiredOption("--issue-id <id>", "Issue identifier")
  .requiredOption("--body <body>", "Comment body");

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

const { issueId, body } = program.opts<CreateCommentOptions>();

async function main() {
  try {
    const client = getLinearClient();

    const commentPayload = await client.createComment({
      issueId,
      body,
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
        issueId,
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
