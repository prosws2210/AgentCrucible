const API = "https://api.github.com";

function headers(): Record<string, string> {
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "github-helper-mcp",
  };
}

export async function gh<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, { ...init, headers: { ...headers(), ...(init.headers ?? {}) } });
  if (!res.ok) throw new Error(`GitHub ${init.method ?? "GET"} ${path} -> ${res.status}: ${await res.text()}`);
  return (await res.json()) as T;
}

export const repoPath = (repo: string) => `/repos/${repo}`;
