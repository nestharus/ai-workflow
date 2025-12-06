#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("get-issue")
  .description("Fetch a Linear issue by ID")
  .requiredOption("--issue-id <id>", "Issue identifier")
  .parse();

const options = program.opts();

/**
 * Fetches a Linear issue by the configured CLI option and emits a structured response.
 *
 * On success, calls `respond` with a success payload containing core issue fields
 * (id, identifier, title, description, priority, estimate, url, branchName, timestamps, due date),
 * selected nested relations (team, assignee, state, project, parent) and computed counts
 * (`commentCount`, `childrenCount`). If the issue is not found, calls `respond` with
 * error code `ISSUE_NOT_FOUND`. If an unexpected error occurs, calls `respond` with
 * error code `GET_ISSUE_FAILED` and the error message.
 */
async function main() {
  try {
    const client = getLinearClient();
    const issue = await client.issue(options.issueId);

    if (!issue) {
      respond(error("ISSUE_NOT_FOUND", `Issue ${options.issueId} not found`));
    }

    const team = await issue.team;
    const assignee = await issue.assignee;
    const state = await issue.state;
    const project = await issue.project;
    const comments = await issue.comments();
    const parent = await issue.parent;
    const children = await issue.children();

    respond(
      success({
        id: issue.id,
        identifier: issue.identifier,
        title: issue.title,
        description: issue.description,
        priority: issue.priority,
        estimate: issue.estimate,
        url: issue.url,
        branchName: issue.branchName,
        createdAt: issue.createdAt,
        updatedAt: issue.updatedAt,
        completedAt: issue.completedAt,
        canceledAt: issue.canceledAt,
        dueDate: issue.dueDate,
        team: team
          ? {
              id: team.id,
              name: team.name,
              key: team.key,
            }
          : null,
        assignee: assignee
          ? {
              id: assignee.id,
              name: assignee.name,
              email: assignee.email,
            }
          : null,
        state: state
          ? {
              id: state.id,
              name: state.name,
              type: state.type,
            }
          : null,
        project: project
          ? {
              id: project.id,
              name: project.name,
            }
          : null,
        parent: parent
          ? {
              id: parent.id,
              identifier: parent.identifier,
              title: parent.title,
            }
          : null,
        commentCount: comments.nodes.length,
        childrenCount: children.nodes.length,
      })
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    respond(error("GET_ISSUE_FAILED", message));
  }
}

main();