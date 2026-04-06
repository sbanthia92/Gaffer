const BASE_URL = import.meta.env.VITE_API_URL ?? "";

export async function askGaffer(
  question: string,
  league: string = "fpl",
  fplTeamId: number | null = null
): Promise<string> {
  const res = await fetch(`${BASE_URL}/api/${league}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, fpl_team_id: fplTeamId }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`Server error ${res.status}: ${text}`);
  }

  const data = await res.json();
  return data.answer as string;
}

export async function submitFeedback(
  message: string,
  email: string
): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, email }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`Server error ${res.status}: ${text}`);
  }
}
