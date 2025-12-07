#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("update-issue")
  .description("Update an existing Linear issue")
  .exitOverride()
  .requiredOption("--issue-id <id>", "Issue identifier")
  .option("--title <title>", "Issue title")
  .option("--description <description>", "Issue description")
  .option("--body <body>", "Issue description (alias for --description)")
  .option("--assignee <assignee>", "Assignee user ID")
  .option("--project <project>", "Project ID")
  .option("--priority <priority>", "Priority (0-4: 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low)", (value) => {
    if (!/^[0-4]$/.test(value)) {
      throw new Error("Priority must be an integer between 0 and 4");
    }
    return Number(value);
  })
  .option("--state <state>", "State ID")
  .option("--parent-id <parentId>", "Parent issue ID")
  .option("--labels <labels>", "Comma-separated label IDs");

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

    // Prepare update payload
    const updatePayload: {
      title?: string;
      description?: string;
      assigneeId?: string;
      projectId?: string;
      priority?: number;
      stateId?: string;
      parentId?: string;
      labelIds?: string[];
    } = {};

    if (options.title) {
      updatePayload.title = options.title;
    }

    // Support both --description and --body (--description takes precedence)
    const description = options.description || options.body;
    if (description) {
      updatePayload.description = description;
    }

    if (options.assignee) {
      updatePayload.assigneeId = options.assignee;
    }

    if (options.project) {
      updatePayload.projectId = options.project;
    }

    if (options.priority !== undefined) {
      updatePayload.priority = options.priority;
    }

    if (options.state) {
      updatePayload.stateId = options.state;
    }

    if (options.parentId) {
      updatePayload.parentId = options.parentId;
    }

    if (options.labels !== undefined) {
      updatePayload.labelIds = options.labels
        .split(",")
        .map((l: string) => l.trim())
        .filter((l: string) => l.length > 0);
    }

    // Check if there are any updates to apply
    if (Object.keys(updatePayload).length === 0) {
      respond(error("NO_UPDATES", "No fields provided to update"));
      return;
    }

    const issuePayload = await client.updateIssue(options.issueId, updatePayload);
    const issue = await issuePayload.issue;

    if (!issue) {
      respond(error("UPDATE_ISSUE_FAILED", `Failed to update issue ${options.issueId}`));
      return;
    }

    respond(
      success({
        id: issue.id,
        identifier: issue.identifier,
        title: issue.title,
        url: issue.url,
        updatedAt: issue.updatedAt,
      })
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    respond(error("UPDATE_ISSUE_FAILED", message));
  }
}

main();
