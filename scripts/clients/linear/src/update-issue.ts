#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("update-issue")
  .description("Update an existing Linear issue")
  .requiredOption("--issue-id <id>", "Issue identifier")
  .option("--title <title>", "Issue title")
  .option("--body <body>", "Issue description")
  .option("--assignee <assignee>", "Assignee user ID")
  .option("--project <project>", "Project ID")
  .option("--priority <priority>", "Priority (0-4: 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low)", parseInt)
  .option("--state <state>", "State ID")
  .option("--parent-id <parentId>", "Parent issue ID")
  .option("--labels <labels>", "Comma-separated label IDs")
  .parse();

const options = program.opts();

/**
 * Update an existing Linear issue using the parsed CLI options and emit a standardized response.
 *
 * Validates that provided priority is between 0 and 4 and requires at least one updatable field.
 * On success, emits a success response containing the issue's `id`, `identifier`, `title`, `url`, and `updatedAt`.
 * On validation failure or if the update fails, emits an error response with an appropriate error code
 * (`INVALID_PRIORITY`, `NO_UPDATES`, or `UPDATE_ISSUE_FAILED`).
 */
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

    if (options.body) {
      updatePayload.description = options.body;
    }

    if (options.assignee) {
      updatePayload.assigneeId = options.assignee;
    }

    if (options.project) {
      updatePayload.projectId = options.project;
    }

    if (options.priority !== undefined) {
      if (options.priority < 0 || options.priority > 4) {
        respond(error("INVALID_PRIORITY", "Priority must be between 0 and 4"));
      }
      updatePayload.priority = options.priority;
    }

    if (options.state) {
      updatePayload.stateId = options.state;
    }

    if (options.parentId) {
      updatePayload.parentId = options.parentId;
    }

    if (options.labels) {
      updatePayload.labelIds = options.labels.split(",").map((l: string) => l.trim());
    }

    // Check if there are any updates to apply
    if (Object.keys(updatePayload).length === 0) {
      respond(error("NO_UPDATES", "No fields provided to update"));
    }

    const issuePayload = await client.updateIssue(options.issueId, updatePayload);
    const issue = await issuePayload.issue;

    if (!issue) {
      respond(error("UPDATE_ISSUE_FAILED", `Failed to update issue ${options.issueId}`));
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