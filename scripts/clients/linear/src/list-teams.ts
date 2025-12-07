#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("list-teams")
  .description("List available Linear teams")
  .exitOverride()
  .option("--include-archived", "Include archived teams", false);

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

    const filter: {
      includeArchived?: boolean;
    } = {};

    if (options.includeArchived) {
      filter.includeArchived = true;
    }

    const teamsConnection = await client.teams(filter);

    const teams = teamsConnection.nodes.map((team) => ({
      id: team.id,
      name: team.name,
      key: team.key,
      description: team.description,
      createdAt: team.createdAt,
      updatedAt: team.updatedAt,
      archivedAt: team.archivedAt,
      private: team.private,
      timezone: team.timezone,
    }));

    respond(
      success({
        teams,
        totalCount: teams.length,
      })
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    respond(error("LIST_TEAMS_FAILED", message));
  }
}

main();
