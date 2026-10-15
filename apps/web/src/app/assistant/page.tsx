"use client";

import { useEffect, useState } from "react";

import { api, watch } from "@/lib/api";
import type { ProposalView } from "@/lib/contracts";

type ChatResponse = {
  events: { kind: string; text: string }[];
  proposal: ProposalView | null;
};

export default function AssistantPage() {
  const [provider, setProvider] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [text, setText] = useState("Draft an SMA cross on AAPL");
  const [events, setEvents] = useState<ChatResponse["events"]>([]);
  const [proposal, setProposal] = useState<ProposalView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  useEffect(
    () =>
      watch<{ enabled: boolean; provider: string; model: string }>(
        "/assistant/status",
        (status) => {
          setProvider(status.provider);
          setModel(status.model);
          setError(null);
        },
        setError,
      ),
    [],
  );

  async function send() {
    setError(null);
    try {
      const response = await api<ChatResponse>("/assistant/chat", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      setEvents(response.events);
      setProposal(response.proposal);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "chat failed");
    }
  }

  async function approve() {
    if (!proposal) {
      return;
    }
    const approved = await api<{ id: string }>(`/assistant/proposals/${proposal.id}/approve`, {
      method: "POST",
    });
    setResult(`Approved. Created ${approved.id}. Nothing was written before this click.`);
    setProposal(null);
  }

  let billing = "Checking the provider.";
  if (provider === "scripted") {
    billing = "No provider key is saved, so this turn uses the local script. A saved key sends the turn to that provider.";
  } else if (provider) {
    billing = model ? `This turn bills your ${provider} key (${model}).` : `This turn bills your ${provider} key.`;
  }

  return (
    <div className="space-y-4">
      <h1 className="text-[28px] font-medium">Assistant</h1>
      <p className="text-sm text-muted">
        Calls bill your own provider key. Samar does not keep a server key. Drafts wait for approval.
      </p>
      <p className="text-sm text-muted">{billing}</p>
      {error ? <p className="text-sm text-loss">{error}</p> : null}
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        className="h-24 w-full rounded-md border border-line bg-surface p-3 text-sm"
      />
      <button type="button" onClick={() => void send()} className="rounded-md bg-accent px-3 py-2 text-sm text-bg">
        Send
      </button>
      <ul className="space-y-2">
        {events.map((event, index) => (
          <li key={`${event.kind}-${index}`} className="text-sm">
            <span className="text-muted">{event.kind}. </span>
            {event.text}
          </li>
        ))}
      </ul>
      {proposal ? (
        <div className="rounded-md border border-line bg-surface p-4">
          <p className="text-sm">Proposal {proposal.kind}</p>
          <p className="num mt-1 text-xs text-muted">{JSON.stringify(proposal.payload)}</p>
          <button type="button" onClick={() => void approve()} className="mt-3 text-sm text-accent">
            Approve
          </button>
        </div>
      ) : null}
      {result ? <p className="text-sm">{result}</p> : null}
    </div>
  );
}
