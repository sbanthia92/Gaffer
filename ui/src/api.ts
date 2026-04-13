const BASE_URL = import.meta.env.VITE_API_URL ?? "";

/**
 * Ask The Gaffer a question. Streams the answer via SSE.
 *
 * @param onChunk  Called with each text chunk as it arrives
 * @returns        The full answer string once streaming is complete
 */
export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export async function askGaffer(
  question: string,
  league: string = "fpl",
  fplTeamId: number | null = null,
  onChunk: (chunk: string) => void = () => {},
  onStatus: (status: string) => void = () => {},
  history: HistoryMessage[] = [],
  version: 1 | 2 = 1
): Promise<string> {
  const res = await fetch(`${BASE_URL}/api/${league}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, fpl_team_id: fplTeamId, history, version }),
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`Server error ${res.status}: ${text}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let fullAnswer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by \n\n
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const eventLine = frame.match(/^event: (\w+)/m)?.[1];
      const dataLine = frame.match(/^data: (.+)/m)?.[1];
      if (!dataLine) continue;

      const data: string = JSON.parse(dataLine);

      if (eventLine === "chunk") {
        fullAnswer += data;
        onChunk(data);
      } else if (eventLine === "status") {
        onStatus(data);
      } else if (eventLine === "error") {
        throw new Error(data);
      }
      // "done" event — nothing to do, loop exits naturally
    }
  }

  return fullAnswer;
}

export interface PlayerCard {
  id: number;
  name: string;
  full_name: string;
  team: string;
  position: string;
  price: number;
  form: string;
  total_points: number;
  selected_by_percent: string;
  photo_url: string;
}

export async function fetchPlayerCard(name: string): Promise<PlayerCard | null> {
  const res = await fetch(
    `${BASE_URL}/api/fpl/player-card?name=${encodeURIComponent(name)}`
  );
  if (!res.ok) return null;
  return res.json();
}

export async function submitContact(
  name: string,
  email: string,
  message: string
): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/contact`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, message }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`Server error ${res.status}: ${text}`);
  }
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
