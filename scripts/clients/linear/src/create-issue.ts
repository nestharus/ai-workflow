#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("create-issue")
  .description("Create a new Linear issue")
  .requiredOption("--title <title>", "Issue title")
  .requiredOption("--team <team>", "Team name or ID")
  .option("--body <body>", "Issue description")
  .option("--assignee <assignee>", "Assignee user ID")
  .option("--project <project>", "Project ID")
  .option("--priority <priority>", "Priority (0-4: 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low)", parseInt)
  .option("--state <state>", "State ID")
  .option("--parent-id <parentId>", "Parent issue ID")
  .option("--labels <labels>", "Comma-separated label IDs")
  .parse();

const options = program.opts();

async function main() {
  try {
    const client = getLinearClient();

    // Prepare create payload
    const createPayload: {
      teamId: string;
      title: string;
      description?: string;
      assigneeId?: string;
      projectId?: string;
      priority?: number;
      stateId?: string;
      parentId?: string;
      labelIds?: string[];
    } = {
      teamId: options.team,
      title: options.title,
    };

    if (options.body) {
      createPayload.description = options.body;
    }

    if (options.assignee) {
      createPayload.assigneeId = options.assignee;
    }

    if (options.project) {
      createPayload.projectId = options.project;
    }

    if (options.priority !== undefined) {
      if (options.priority < 0 || options.priority > 4) {
        respond(error("INVALID_PRIORITY", "Priority must be between 0 and 4"));
      }
      createPayload.priority = options.priority;
    }

    if (options.state) {
      createPayload.stateId = options.state;
    }

    if (options.parentId) {
      createPayload.parentId = options.parentId;
    }

    if (options.labels) {
      createPayload.labelIds = options.labels.split(",").map((l: string) => l.trim());
    }

    const issuePayload = await client.createIssue(createPayload);
    const issue = await issuePayload.issue;

    if (!issue) {
      respond(error("CREATE_ISSUE_FAILED", "Failed to create issue"));
    }

    respond(
      success({
        id: issue.id,
        identifier: issue.identifier,
        title: issue.title,
        url: issue.url,
        branchName: issue.branchName,
      })
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    respond(error("CREATE_ISSUE_FAILED", message));
  }
}

main();
