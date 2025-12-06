#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("list-teams")
  .description("List available Linear teams")
  .option("--include-archived", "Include archived teams", false)
  .parse();

const options = program.opts();

/**
 * Fetches teams from the Linear client and sends a structured response.
 *
 * Fetches a list of teams (optionally including archived teams), maps each team to a plain object
 * containing selected fields (id, name, key, description, createdAt, updatedAt, archivedAt, private, timezone),
 * and sends the result via `respond`. On error, sends an error payload with code `LIST_TEAMS_FAILED`.
 */
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

    const teams = await Promise.all(
      teamsConnection.nodes.map(async (team) => {
        return {
          id: team.id,
          name: team.name,
          key: team.key,
          description: team.description,
          createdAt: team.createdAt,
          updatedAt: team.updatedAt,
          archivedAt: team.archivedAt,
          private: team.private,
          timezone: team.timezone,
        };
      })
    );

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