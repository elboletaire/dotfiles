// Cuts a markdown message for the bubble at a word or line boundary, closing any
// fence or emphasis the cut left open, so the rest still renders.
export const MAX_LINES = 6;
export const MAX_CHARS = 280;

const count = (text, marker) => text.split(marker).length - 1;

export function clip(text, maxLines = MAX_LINES, maxChars = MAX_CHARS) {
  if (text.split("\n").length <= maxLines && text.length <= maxChars) return text;
  let cut = text.split("\n").slice(0, maxLines).join("\n");
  if (cut.length > maxChars) {
    cut = cut.slice(0, maxChars);
    // Back up to the last space when the cut landed inside a word.
    const word = cut.search(/\s\S*$/);
    if (word > maxChars / 2) cut = cut.slice(0, word);
  }
  cut = cut.trimEnd();
  if (count(cut, "```") % 2) return `${cut}\n\`\`\`\n…*more*`;
  for (const marker of ["`", "**", "*", "_"]) {
    if (count(cut, marker) % 2) cut = cut.slice(0, cut.lastIndexOf(marker)).trimEnd();
  }
  return `${cut} …*more*`;
}
