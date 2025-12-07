import { LinearClient } from "@linear/sdk";

/**
 * Factory function for creating LinearClient instances.
 * This is exposed for testing purposes to allow mocking.
 *
 * @param apiKey - The Linear API key
 * @returns {LinearClient} New Linear client instance
 */
export function createLinearClient(apiKey: string): LinearClient {
  return new LinearClient({ apiKey });
}

/**
 * Creates and returns a configured Linear client instance.
 * Reads the API key from the LINEAR_API_KEY environment variable.
 *
 * If LINEAR_API_KEY is not set, outputs a JSON error with code MISSING_API_KEY
 * and exits with code 1. This ensures the Python wrapper receives structured
 * error output rather than a raw stack trace.
 *
 * @returns {LinearClient} Configured Linear client (exits on error)
 */
export function getLinearClient(): LinearClient {
  const apiKey = process.env.LINEAR_API_KEY;

  if (!apiKey) {
    respond(error("MISSING_API_KEY", "LINEAR_API_KEY environment variable is not set"));
  }

  return createLinearClient(apiKey);
}

/**
 * Standard success response structure
 */
export interface SuccessResponse<T = unknown> {
  ok: true;
  data: T;
}

/**
 * Standard error response structure
 */
export interface ErrorResponse {
  ok: false;
  error: {
    code: string;
    message: string;
  };
}

/**
 * Union type for all responses
 */
export type Response<T = unknown> = SuccessResponse<T> | ErrorResponse;

/**
 * Helper to create a success response
 */
export function success<T>(data: T): SuccessResponse<T> {
  return { ok: true, data };
}

/**
 * Helper to create an error response
 */
export function error(code: string, message: string): ErrorResponse {
  return { ok: false, error: { code, message } };
}

/**
 * Helper to output response and exit with appropriate code.
 * Uses process.stdout.write with a callback to ensure the JSON output
 * is fully flushed before exiting, preventing dropped buffered stdout.
 */
export function respond<T>(response: Response<T>): void {
  const data = JSON.stringify(response, null, 2) + "\n";
  process.stdout.write(data, () => {
    process.exit(response.ok ? 0 : 1);
  });
}
