import { LinearClient } from "@linear/sdk";

/**
 * Creates and returns a configured Linear client instance.
 * Reads the API key from the LINEAR_API_KEY environment variable.
 *
 * @throws {Error} If LINEAR_API_KEY is not set
 * @returns {LinearClient} Configured Linear client
 */
export function getLinearClient(): LinearClient {
  const apiKey = process.env.LINEAR_API_KEY;

  if (!apiKey) {
    throw new Error("LINEAR_API_KEY environment variable is not set");
  }

  return new LinearClient({ apiKey });
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
 * Helper to output response and exit with appropriate code
 */
export function respond<T>(response: Response<T>): never {
  console.log(JSON.stringify(response, null, 2));
  process.exit(response.ok ? 0 : 1);
}
