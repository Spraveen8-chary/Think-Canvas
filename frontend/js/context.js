// Conversation context on the canvas. Writing the AI has already answered is marked `done`; when the student
// continues near it, the new writing is the question and the old writing is only context.
// Pure functions (no browser code), so they can be unit-tested in Node.

// -> { fresh, done, reread }. Nothing new (e.g. "Answer now" on an answered spot) means: read everything again.
export function splitContext(near) {
  const fresh = near.filter((i) => !i.done);
  if (!fresh.length) return { fresh: near, done: [], reread: true };
  return { fresh, done: near.filter((i) => i.done), reread: false };
}

export const textOf = (items) => items.filter((i) => i.type === "text").map((i) => i.text).join("\n");
export const hasInk = (items) => items.some((i) => i.type === "stroke" || i.type === "image");
