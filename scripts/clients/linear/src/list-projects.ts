#!/usr/bin/env node
/**
 * List available Linear projects.
 *
 * Note: This script returns only the first page of results from the Linear API.
 * For workspaces with many projects, not all projects may be returned.
 *
 * When --team is specified, projects are fetched from that team directly
 * (server-side filtering) to avoid N+1 API calls.
 */
import { Command } from "commander";
import { Project } from "@linear/sdk";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("list-projects")
  .description("List available Linear projects")
  .exitOverride()
  .option("--team <team>", "Filter by team ID")
  .option("--include-archived", "Include archived projects", false);

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

interface ProjectData {
  id: string;
  name: string;
  description: string | undefined;
  url: string;
  slugId: string;
  startedAt: Date | undefined;
  completedAt: Date | undefined;
  targetDate: string | undefined;
  createdAt: Date;
  updatedAt: Date;
  archivedAt: Date | undefined;
  lead: { id: string; name: string; email: string } | null;
  state: string | null;
  teams: Array<{ id: string; name: string; key: string }>;
}

async function mapProject(project: Project, teamData?: { id: string; name: string; key: string }): Promise<ProjectData> {
  const lead = await project.lead;

  // If teamData is provided (from team.projects), use it directly
  // Otherwise, fetch teams for this project
  let teams: Array<{ id: string; name: string; key: string }> = [];
  if (teamData) {
    teams = [teamData];
  } else {
    const teamsConnection = await project.teams();
    if (teamsConnection) {
      teams = teamsConnection.nodes.map((t: any) => ({
        id: t.id,
        name: t.name,
        key: t.key,
      }));
    }
  }

  return {
    id: project.id,
    name: project.name,
    description: project.description,
    url: project.url,
    slugId: project.slugId,
    startedAt: project.startedAt,
    completedAt: project.completedAt,
    targetDate: project.targetDate,
    createdAt: project.createdAt,
    updatedAt: project.updatedAt,
    archivedAt: project.archivedAt,
    lead: lead
      ? {
          id: lead.id,
          name: lead.name,
          email: lead.email,
        }
      : null,
    state: project.state || null,
    teams,
  };
}

async function main() {
  try {
    const client = getLinearClient();

    let projects: ProjectData[];

    if (options.team) {
      // Server-side filtering: fetch projects from the specified team directly
      // This avoids N+1 by not needing to fetch teams for each project
      const team = await client.team(options.team);
      if (!team) {
        respond(error("TEAM_NOT_FOUND", `Team ${options.team} not found`));
        return;
      }

      const teamData = { id: team.id, name: team.name, key: team.key };
      const projectsConnection = await team.projects({
        includeArchived: options.includeArchived || false,
      });

      projects = await Promise.all(
        projectsConnection.nodes.map((project) => mapProject(project, teamData))
      );
    } else {
      // No team filter: fetch all projects
      const projectsConnection = await client.projects({
        includeArchived: options.includeArchived || false,
      });

      projects = await Promise.all(
        projectsConnection.nodes.map((project) => mapProject(project))
      );
    }

    respond(
      success({
        projects,
        totalCount: projects.length,
      })
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    respond(error("LIST_PROJECTS_FAILED", message));
  }
}

main();
