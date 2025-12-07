/**
 * Unit tests for the Linear TypeScript client helper functions and configuration.
 *
 * These tests verify the helper functions (success, error), response shape contracts,
 * and client initialization without requiring a real Linear API key or network calls.
 */

import { describe, it, before, after, mock } from "node:test";
import assert from "node:assert";
import { success, error, getLinearClient, createLinearClient } from "../client.js";

describe("Helper Functions", () => {
  describe("success()", () => {
    it("should create a success response with the provided data", () => {
      const data = { id: "test-id", title: "Test Issue" };
      const response = success(data);

      assert.strictEqual(response.ok, true);
      assert.deepStrictEqual(response.data, data);
    });

    it("should handle empty data object", () => {
      const response = success({});

      assert.strictEqual(response.ok, true);
      assert.deepStrictEqual(response.data, {});
    });

    it("should handle complex nested data", () => {
      const data = {
        id: "issue-123",
        team: { id: "team-1", name: "Engineering" },
        labels: [{ id: "label-1", name: "bug" }],
      };
      const response = success(data);

      assert.strictEqual(response.ok, true);
      assert.deepStrictEqual(response.data, data);
    });

    it("should handle array data", () => {
      const data = [{ id: "1" }, { id: "2" }];
      const response = success(data);

      assert.strictEqual(response.ok, true);
      assert.deepStrictEqual(response.data, data);
    });
  });

  describe("error()", () => {
    it("should create an error response with code and message", () => {
      const response = error("NOT_FOUND", "Issue not found");

      assert.strictEqual(response.ok, false);
      assert.strictEqual(response.error.code, "NOT_FOUND");
      assert.strictEqual(response.error.message, "Issue not found");
    });

    it("should handle empty message", () => {
      const response = error("UNKNOWN_ERROR", "");

      assert.strictEqual(response.ok, false);
      assert.strictEqual(response.error.code, "UNKNOWN_ERROR");
      assert.strictEqual(response.error.message, "");
    });

    it("should preserve special characters in message", () => {
      const message = "Error: file \"test.ts\" not found at /path/to/file";
      const response = error("FILE_ERROR", message);

      assert.strictEqual(response.error.message, message);
    });
  });
});

describe("Response Shape Contracts", () => {
  it("should have standard success response structure", () => {
    const successResponse = success({
      id: "test-id",
      title: "Test Issue",
    });

    assert.strictEqual(successResponse.ok, true);
    assert.ok(successResponse.data);
    assert.strictEqual(successResponse.data.id, "test-id");
  });

  it("should have standard error response structure", () => {
    const errorResponse = error("NOT_FOUND", "Issue not found");

    assert.strictEqual(errorResponse.ok, false);
    assert.ok(errorResponse.error);
    assert.strictEqual(errorResponse.error.code, "NOT_FOUND");
    assert.strictEqual(errorResponse.error.message, "Issue not found");
  });
});

describe("Error Codes", () => {
  const errorCodes = [
    { code: "MISSING_API_KEY", description: "API key not provided" },
    { code: "UNAUTHORIZED", description: "Invalid API key" },
    { code: "NOT_FOUND", description: "Resource not found" },
    { code: "INVALID_INPUT", description: "Invalid input parameters" },
    { code: "PARSE_ERROR", description: "JSON parsing failed" },
    { code: "UNKNOWN_ERROR", description: "Unknown error occurred" },
    { code: "NO_UPDATES", description: "No fields provided to update" },
    { code: "ISSUE_NOT_FOUND", description: "Issue not found" },
    { code: "CREATE_ISSUE_FAILED", description: "Failed to create issue" },
    { code: "UPDATE_ISSUE_FAILED", description: "Failed to update issue" },
    { code: "CREATE_COMMENT_FAILED", description: "Failed to create comment" },
    { code: "LIST_COMMENTS_FAILED", description: "Failed to list comments" },
    { code: "LIST_PROJECTS_FAILED", description: "Failed to list projects" },
    { code: "LIST_TEAMS_FAILED", description: "Failed to list teams" },
  ];

  it("should create valid error responses for all known error codes", () => {
    errorCodes.forEach((errorType) => {
      const errorResponse = error(errorType.code, errorType.description);

      assert.strictEqual(errorResponse.ok, false);
      assert.strictEqual(errorResponse.error.code, errorType.code);
      assert.strictEqual(errorResponse.error.message, errorType.description);
    });
  });
});

describe("getLinearClient", () => {
  let originalApiKey: string | undefined;
  let originalExit: typeof process.exit;
  let originalLog: typeof console.log;
  let capturedOutput: string | undefined;
  let capturedExitCode: number | undefined;

  before(() => {
    originalApiKey = process.env.LINEAR_API_KEY;
    originalExit = process.exit;
    originalLog = console.log;
  });

  after(() => {
    if (originalApiKey !== undefined) {
      process.env.LINEAR_API_KEY = originalApiKey;
    } else {
      delete process.env.LINEAR_API_KEY;
    }
    process.exit = originalExit;
    console.log = originalLog;
  });

  it("should output MISSING_API_KEY error and exit when API key is missing", () => {
    delete process.env.LINEAR_API_KEY;
    capturedOutput = undefined;
    capturedExitCode = undefined;

    // Mock console.log and process.exit to capture output
    console.log = (output: string) => {
      capturedOutput = output;
    };
    process.exit = ((code?: number) => {
      capturedExitCode = code;
      throw new Error("process.exit called");
    }) as typeof process.exit;

    assert.throws(
      () => getLinearClient(),
      { message: "process.exit called" }
    );

    assert.strictEqual(capturedExitCode, 1);
    assert.ok(capturedOutput);
    const parsed = JSON.parse(capturedOutput);
    assert.strictEqual(parsed.ok, false);
    assert.strictEqual(parsed.error.code, "MISSING_API_KEY");
    assert.strictEqual(parsed.error.message, "LINEAR_API_KEY environment variable is not set");
  });

  it("should output MISSING_API_KEY error when API key is empty string", () => {
    process.env.LINEAR_API_KEY = "";
    capturedOutput = undefined;
    capturedExitCode = undefined;

    // Mock console.log and process.exit to capture output
    console.log = (output: string) => {
      capturedOutput = output;
    };
    process.exit = ((code?: number) => {
      capturedExitCode = code;
      throw new Error("process.exit called");
    }) as typeof process.exit;

    assert.throws(
      () => getLinearClient(),
      { message: "process.exit called" }
    );

    assert.strictEqual(capturedExitCode, 1);
    assert.ok(capturedOutput);
    const parsed = JSON.parse(capturedOutput);
    assert.strictEqual(parsed.ok, false);
    assert.strictEqual(parsed.error.code, "MISSING_API_KEY");
  });
});

describe("createLinearClient Factory", () => {
  it("should be a function that accepts an API key", () => {
    assert.strictEqual(typeof createLinearClient, "function");
    assert.strictEqual(createLinearClient.length, 1);
  });

  it("should return a LinearClient instance when given a valid key", () => {
    const validKey = "test-linear-api-key";
    const client = createLinearClient(validKey);

    assert.ok(client, "Client should be created");
    assert.strictEqual(typeof client, "object");
  });
});

describe("Issue Response Structure", () => {
  it("should have complete get_issue response fields", () => {
    const issueResponse = success({
      id: "issue-123",
      identifier: "NES-24",
      title: "Test Issue",
      description: "Test description",
      priority: 2,
      estimate: null,
      url: "https://linear.app/issue/NES-24",
      branchName: "nes-24-test-issue",
      createdAt: "2025-01-01T00:00:00Z",
      updatedAt: "2025-01-02T00:00:00Z",
      completedAt: null,
      canceledAt: null,
      dueDate: null,
      team: { id: "team-1", name: "Engineering", key: "ENG" },
      assignee: { id: "user-1", name: "Test User", email: "test@example.com" },
      state: { id: "state-1", name: "In Progress", type: "started" },
      project: { id: "project-1", name: "Test Project" },
      parent: null,
      commentCount: 5,
      childrenCount: 0,
    });

    assert.strictEqual(issueResponse.ok, true);
    assert.strictEqual(issueResponse.data.identifier, "NES-24");
    assert.strictEqual(issueResponse.data.team.key, "ENG");
    assert.strictEqual(issueResponse.data.state.type, "started");
  });

  it("should have complete create_issue response fields", () => {
    const createResponse = success({
      id: "issue-new",
      identifier: "NES-99",
      title: "New Feature",
      url: "https://linear.app/issue/NES-99",
      branchName: "nes-99-new-feature",
    });

    assert.strictEqual(createResponse.ok, true);
    assert.ok(createResponse.data.id);
    assert.ok(createResponse.data.identifier);
    assert.ok(createResponse.data.branchName);
  });

  it("should have complete update_issue response fields", () => {
    const updateResponse = success({
      id: "issue-123",
      identifier: "NES-24",
      title: "Updated Title",
      url: "https://linear.app/issue/NES-24",
      updatedAt: "2025-01-03T00:00:00Z",
    });

    assert.strictEqual(updateResponse.ok, true);
    assert.ok(updateResponse.data.updatedAt);
  });
});

describe("Project Response Structure", () => {
  it("should have complete list_projects response fields", () => {
    const projectsResponse = success({
      projects: [
        {
          id: "project-1",
          name: "Project Alpha",
          description: "First project",
          url: "https://linear.app/project/alpha",
          slugId: "alpha",
          startedAt: "2025-01-01T00:00:00Z",
          completedAt: null,
          targetDate: "2025-06-01",
          createdAt: "2025-01-01T00:00:00Z",
          updatedAt: "2025-01-02T00:00:00Z",
          archivedAt: null,
          lead: { id: "user-1", name: "Lead User", email: "lead@example.com" },
          state: "started",
          teams: [{ id: "team-1", name: "Engineering", key: "ENG" }],
        },
      ],
      totalCount: 1,
    });

    assert.strictEqual(projectsResponse.ok, true);
    assert.strictEqual(projectsResponse.data.projects.length, 1);
    assert.ok(projectsResponse.data.projects[0].slugId);
    assert.ok(projectsResponse.data.projects[0].teams);
  });
});

describe("Team Response Structure", () => {
  it("should have complete list_teams response fields", () => {
    const teamsResponse = success({
      teams: [
        {
          id: "team-1",
          name: "Engineering",
          key: "ENG",
          description: "Engineering team",
          createdAt: "2025-01-01T00:00:00Z",
          updatedAt: "2025-01-02T00:00:00Z",
          archivedAt: null,
          private: false,
          timezone: "America/New_York",
        },
      ],
      totalCount: 1,
    });

    assert.strictEqual(teamsResponse.ok, true);
    assert.strictEqual(teamsResponse.data.teams.length, 1);
    assert.strictEqual(teamsResponse.data.teams[0].key, "ENG");
    assert.strictEqual(teamsResponse.data.teams[0].private, false);
  });
});

describe("Comment Response Structure", () => {
  it("should have complete list_comments response fields", () => {
    const commentsResponse = success({
      issueId: "issue-123",
      issueIdentifier: "NES-24",
      comments: [
        {
          id: "comment-1",
          body: "First comment",
          createdAt: "2025-01-01T00:00:00Z",
          updatedAt: "2025-01-01T00:00:00Z",
          user: { id: "user-1", name: "Test User", email: "test@example.com" },
        },
      ],
      totalCount: 1,
    });

    assert.strictEqual(commentsResponse.ok, true);
    assert.ok(commentsResponse.data.issueId);
    assert.ok(commentsResponse.data.issueIdentifier);
    assert.strictEqual(commentsResponse.data.comments.length, 1);
  });

  it("should have complete create_comment response fields", () => {
    const commentResponse = success({
      id: "comment-new",
      body: "New comment",
      createdAt: "2025-01-03T00:00:00Z",
      issueId: "issue-123",
      user: { id: "user-1", name: "Test User", email: "test@example.com" },
    });

    assert.strictEqual(commentResponse.ok, true);
    assert.ok(commentResponse.data.id);
    assert.ok(commentResponse.data.body);
    assert.ok(commentResponse.data.issueId);
  });
});
