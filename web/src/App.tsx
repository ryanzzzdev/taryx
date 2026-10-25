import { useEffect, useState } from "react";

type PingResult =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ok"; ping: string; version: string };

export function App() {
  const [result, setResult] = useState<PingResult>({ state: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch("/graphql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "{ ping version }" }),
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as {
          data?: { ping: string; version: string };
          errors?: { message: string }[];
        };
        if (body.errors?.length) throw new Error(body.errors[0]!.message);
        if (!body.data) throw new Error("empty GraphQL response");
        if (!cancelled) {
          setResult({ state: "ok", ping: body.data.ping, version: body.data.version });
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setResult({ state: "error", message: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>Taryx operator portal</h1>
      {result.state === "loading" && <p>Contacting retail core API…</p>}
      {result.state === "error" && <p role="alert">API unreachable: {result.message}</p>}
      {result.state === "ok" && (
        <p>
          API responded to smoke query: <strong>{result.ping}</strong> (version{" "}
          {result.version})
        </p>
      )}
    </main>
  );
}
