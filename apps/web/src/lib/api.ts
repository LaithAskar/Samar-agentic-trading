export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:43124";

export function authHeader(): Record<string, string> {
  if (typeof window === "undefined") {
    return {};
  }
  const token = sessionStorage.getItem("samar_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeader(),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    let message = detail || `request failed ${response.status}`;
    try {
      const parsed = JSON.parse(detail) as { detail?: unknown };
      if (typeof parsed.detail === "string") {
        message = parsed.detail;
      }
    } catch {
      message = detail || `request failed ${response.status}`;
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function watch<T>(
  path: string,
  onData: (row: T) => void,
  onError: (message: string) => void,
): () => void {
  let current = true;
  api<T>(path)
    .then((row) => {
      if (current) {
        onData(row);
      }
    })
    .catch((reason: unknown) => {
      if (!current) {
        return;
      }
      onError(reason instanceof Error ? reason.message : "offline");
    });
  return () => {
    current = false;
  };
}
