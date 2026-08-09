/* Mints the short-lived WebSocket URL the browser uses to talk to the
   ElevenLabs agent.

   ELEVENLABS_API_KEY is an account-wide credential and deliberately carries no
   NEXT_PUBLIC_ prefix, so it exists only in this process. Nothing here may put
   it — or any upstream body that might quote the request back at us — into a
   response or a log line. The browser only ever receives the signed URL, which
   is scoped to one agent and expires in 15 minutes. */

// Signed URLs expire; a cached copy of this route would hand out dead ones.
export const dynamic = "force-dynamic";

const SIGNED_URL_ENDPOINT = "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url";

export async function GET() {
  const apiKey = process.env.ELEVENLABS_API_KEY?.trim();
  const agentId = process.env.ELEVENLABS_AGENT_ID?.trim();

  // Missing credentials is the expected state before anyone has pasted them in,
  // not a fault — answer it as data the panel can render as instructions.
  if (!apiKey || !agentId) {
    const missing: string[] = [];
    if (!apiKey) missing.push("ELEVENLABS_API_KEY");
    if (!agentId) missing.push("ELEVENLABS_AGENT_ID");
    const plural = missing.length > 1;

    return Response.json(
      {
        configured: false,
        reason: `${missing.join(" and ")} ${plural ? "are" : "is"} not set. Add ${
          plural ? "them" : "it"
        } to frontend/.env.local and restart the dev server.`,
      },
      { status: 503 }
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${SIGNED_URL_ENDPOINT}?agent_id=${encodeURIComponent(agentId)}`, {
      headers: { "xi-api-key": apiKey },
      cache: "no-store",
    });
  } catch {
    // The thrown error is swallowed rather than surfaced: a fetch failure can
    // serialise the whole request object, headers included.
    return Response.json(
      { configured: true, signedUrl: null, reason: "Could not reach the ElevenLabs API." },
      { status: 502 }
    );
  }

  if (!upstream.ok) {
    // Status only. The upstream body is dropped on purpose — an error payload
    // is free to echo the request that carried the key.
    console.error(`[voice/signed-url] ElevenLabs returned HTTP ${upstream.status}`);

    const reason =
      upstream.status === 401 || upstream.status === 403
        ? "ElevenLabs rejected the API key (HTTP 401/403). Check ELEVENLABS_API_KEY."
        : upstream.status === 404
          ? "ElevenLabs did not recognise the agent (HTTP 404). Check ELEVENLABS_AGENT_ID."
          : `ElevenLabs could not issue a signed URL (HTTP ${upstream.status}).`;

    return Response.json({ configured: true, signedUrl: null, reason }, { status: 502 });
  }

  const body = (await upstream.json().catch(() => null)) as { signed_url?: string } | null;

  if (!body?.signed_url) {
    return Response.json(
      { configured: true, signedUrl: null, reason: "ElevenLabs returned no signed URL." },
      { status: 502 }
    );
  }

  return Response.json({ configured: true, signedUrl: body.signed_url });
}
