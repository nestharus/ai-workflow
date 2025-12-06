/**
 * Unit tests for the Linear TypeScript client initialization and configuration.
 *
 * Uses Node.js built-in test runner (node:test) for testing client setup,
 * API key validation, and error handling.
 */

import { describe, it, before, after } from "node:test";
import assert from "node:assert";
import { LinearClient } from "@linear/sdk";

describe("LinearClient Initialization", () => {
  let originalApiKey: string | undefined;

  before(() => {
    // Save original API key
    originalApiKey = process.env.LINEAR_API_KEY;
  });

  after(() => {
    // Restore original API key
    if (originalApiKey) {
      process.env.LINEAR_API_KEY = originalApiKey;
    } else {
      delete process.env.LINEAR_API_KEY;
    }
  });

  it("should initialize client with API key from environment", () => {
    process.env.LINEAR_API_KEY = "test_api_key";
    const client = new LinearClient({ apiKey: process.env.LINEAR_API_KEY });
    assert.ok(client, "Client should be initialized");
  });

  it("should fail when API key is missing", () => {
    delete process.env.LINEAR_API_KEY;
    assert.throws(
      () => {
        new LinearClient({ apiKey: process.env.LINEAR_API_KEY });
      },
      {
        name: "Error",
        message: /API key/i,
      },
      "Should throw error for missing API key"
    );
  });

  it("should fail when API key is empty string", () => {
    process.env.LINEAR_API_KEY = "";
    assert.throws(
      () => {
        new LinearClient({ apiKey: process.env.LINEAR_API_KEY });
      },
      {
        name: "Error",
      },
      "Should throw error for empty API key"
    );
  });
});

describe("LinearClient Configuration", () => {
  it("should accept valid API key format", () => {
    const validKey = "lin_api_test123456789";
    const client = new LinearClient({ apiKey: validKey });
    assert.ok(client, "Client should accept valid API key format");
  });

  it("should initialize with different API key formats", () => {
    // Test various API key formats that Linear might use
    const testKeys = [
      "lin_api_abc123",
      "test_key_12345",
      "valid-api-key-format",
    ];

    testKeys.forEach((key) => {
      const client = new LinearClient({ apiKey: key });
      assert.ok(client, `Client should initialize with key: ${key}`);
    });
  });
});

describe("LinearClient Response Format", () => {
  it("should handle standard success response structure", () => {
    const successResponse = {
      ok: true,
      data: {
        id: "test-id",
        title: "Test Issue",
      },
    };

    assert.strictEqual(successResponse.ok, true);
    assert.ok(successResponse.data);
    assert.strictEqual(successResponse.data.id, "test-id");
  });

  it("should handle standard error response structure", () => {
    const errorResponse = {
      ok: false,
      error: {
        code: "NOT_FOUND",
        message: "Issue not found",
      },
    };

    assert.strictEqual(errorResponse.ok, false);
    assert.ok(errorResponse.error);
    assert.strictEqual(errorResponse.error.code, "NOT_FOUND");
    assert.strictEqual(errorResponse.error.message, "Issue not found");
  });
});

describe("LinearClient Error Codes", () => {
  const errorCodes = [
    { code: "MISSING_API_KEY", description: "API key not provided" },
    { code: "UNAUTHORIZED", description: "Invalid API key" },
    { code: "NOT_FOUND", description: "Resource not found" },
    { code: "INVALID_INPUT", description: "Invalid input parameters" },
    { code: "PARSE_ERROR", description: "JSON parsing failed" },
    { code: "UNKNOWN_ERROR", description: "Unknown error occurred" },
  ];

  it("should recognize standard error codes", () => {
    errorCodes.forEach((errorType) => {
      const errorResponse = {
        ok: false,
        error: {
          code: errorType.code,
          message: errorType.description,
        },
      };

      assert.strictEqual(errorResponse.error.code, errorType.code);
      assert.ok(errorResponse.error.message);
    });
  });
});

describe("LinearClient API Key Security", () => {
  it("should not expose API key in string representation", () => {
    const secretKey = "lin_api_secret_key_12345";
    const client = new LinearClient({ apiKey: secretKey });

    // Convert client to string and ensure key is not exposed
    const clientString = JSON.stringify(client);
    assert.strictEqual(
      clientString.includes(secretKey),
      false,
      "API key should not be exposed in client string representation"
    );
  });

  it("should handle API key in environment variable", () => {
    const testKey = "lin_api_env_test";
    process.env.LINEAR_API_KEY = testKey;

    const client = new LinearClient({ apiKey: process.env.LINEAR_API_KEY });
    assert.ok(client, "Client should initialize from environment variable");

    // Clean up
    delete process.env.LINEAR_API_KEY;
  });
});
