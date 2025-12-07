#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("create-issue")
  .description("Create a new Linear issue")
  .exitOverride()
  .requiredOption("--title <title>", "Issue title")
  .requiredOption("--team <team>", "Team ID (UUID) or team name/key")
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

/**
 * Resolve a team identifier (UUID, name, or key) to a team ID.
 * Returns the team ID if found, or null if not found.
 */
async function resolveTeamId(client: ReturnType<typeof getLinearClient>, team: string): Promise<string | null> {
  // Check if it looks like a UUID (simple heuristic: contains hyphens and is long enough)
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (uuidPattern.test(team)) {
    return team;
  }

  // Otherwise, try to find the team by name or key
  const teamsConnection = await client.teams();
  const teams = teamsConnection.nodes;

  // Try exact match by key first (case-insensitive)
  const byKey = teams.find((t) => t.key.toLowerCase() === team.toLowerCase());
  if (byKey) {
    return byKey.id;
  }

  // Then try exact match by name (case-insensitive)
  const byName = teams.find((t) => t.name.toLowerCase() === team.toLowerCase());
  if (byName) {
    return byName.id;
  }

  return null;
}

async function main() {
  try {
    const client = getLinearClient();

    // Validate and trim required fields
    const title = options.title?.trim();
    const team = options.team?.trim();

    if (!title) {
      respond(error("INVALID_INPUT", "Title cannot be empty"));
      return;
    }

    if (!team) {
      respond(error("INVALID_INPUT", "Team cannot be empty"));
      return;
    }

    // Resolve team name/key to ID
    const teamId = await resolveTeamId(client, team);
    if (!teamId) {
      respond(error("INVALID_INPUT", `Team not found: ${team}`));
      return;
    }

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
      teamId: teamId,
      title: title,
    };

    // Support both --description and --body (--description takes precedence)
    const description = options.description || options.body;
    if (description) {
      createPayload.description = description;
    }

    if (options.assignee) {
      createPayload.assigneeId = options.assignee;
    }

    if (options.project) {
      createPayload.projectId = options.project;
    }

    if (options.priority !== undefined) {
      createPayload.priority = options.priority;
    }

    if (options.state) {
      createPayload.stateId = options.state;
    }

    if (options.parentId) {
      createPayload.parentId = options.parentId;
    }

    if (options.labels) {
      const labelIds = options.labels
        .split(",")
        .map((l: string) => l.trim())
        .filter((l: string) => l.length > 0);
      if (labelIds.length > 0) {
        createPayload.labelIds = labelIds;
      }
    }

    const issuePayload = await client.createIssue(createPayload);
    const issue = await issuePayload.issue;

    if (!issue) {
      respond(error("CREATE_ISSUE_FAILED", "Failed to create issue"));
      return;
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
