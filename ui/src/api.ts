const BASE_URL = import.meta.env.VITE_API_URL ?? "";

export async function askGaffer(
  question: string,
  league: string = "fpl"
): Promise<string> {
  const res = await fetch(`${BASE_URL}/api/${league}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`Server error ${res.status}: ${text}`);
  }

  const data = await res.json();
  return data.answer as string;
}
