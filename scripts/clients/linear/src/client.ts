import { LinearClient } from "@linear/sdk";

/**
 * Obtain a Linear client configured with the LINEAR_API_KEY environment variable.
 *
 * @throws Error If the `LINEAR_API_KEY` environment variable is not set.
 * @returns A `LinearClient` configured with the `LINEAR_API_KEY` value.
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
 * Create a success response object containing the given data.
 *
 * @param data - The payload to include in the response
 * @returns A `SuccessResponse` with `ok: true` and `data` set to the provided value
 */
export function success<T>(data: T): SuccessResponse<T> {
  return { ok: true, data };
}

/**
 * Create a standardized error response object with an error code and human-readable message.
 *
 * @param code - Machine-readable error code
 * @param message - Human-readable error message
 * @returns An `ErrorResponse` with `ok: false` and an `error` object containing `code` and `message`
 */
export function error(code: string, message: string): ErrorResponse {
  return { ok: false, error: { code, message } };
}

/**
 * Writes `response` as pretty-printed JSON to stdout and terminates the process with an exit code indicating success.
 *
 * @param response - The response object to output; exits with code `0` when `response.ok` is `true`, otherwise exits with code `1`.
 */
export function respond<T>(response: Response<T>): never {
  console.log(JSON.stringify(response, null, 2));
  process.exit(response.ok ? 0 : 1);
}