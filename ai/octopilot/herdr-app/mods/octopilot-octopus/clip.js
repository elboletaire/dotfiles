// Cuts a markdown message for the bubble at a word or line boundary, closing any
// fence, inline code or emphasis the cut left open, so the rest still renders.
export const MAX_LINES = 6;
export const MAX_CHARS = 280;

const count = (text, marker) => text.split(marker).length - 1;
const blank = (match) => match.replace(/[^\n]/g, "x");
const WORD = /[\p{L}\p{N}]/u;
const SPACE = /\s/;

// Emphasis markers still open at the end of `masked` (code already blanked out),
// outermost first. A marker only counts at a word edge, so "MAX_ACTIVE",
// "view_json" and "* item" bullets are left alone.
function openEmphasis(masked) {
  let stack = [];
  for (const line of masked.split("\n")) {
    if (!line.trim()) { stack = []; continue; }
    const start = line.match(/^\s*[*+-]\s/)?.[0].length ?? 0;
    for (const m of line.matchAll(/\*+|_+/g)) {
      if (m.index < start) continue;
      const marker = m[0];
      const before = line[m.index - 1] ?? " ";
      const after = line[m.index + marker.length] ?? " ";
      const canOpen = !SPACE.test(after) && !WORD.test(before) && before !== marker[0];
      const canClose = !SPACE.test(before) && !WORD.test(after) && after !== marker[0];
      const at = stack.lastIndexOf(marker);
      if (canClose && at >= 0) stack = stack.slice(0, at);
      else if (canOpen) stack.push(marker);
      else if (canClose && m.index + marker.length === line.length && stack.length) {
        // A cut inside a closing "**" leaves a lone "*": finish the marker.
        const top = stack[stack.length - 1];
        if (top[0] === marker[0] && top.length > marker.length) {
          stack[stack.length - 1] = top.slice(marker.length);
        }
      }
    }
  }
  return stack;
}

export function clip(text, maxLines = MAX_LINES, maxChars = MAX_CHARS) {
  if (text.endsWith("…*more*")) return text;
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

  // Inline code first: close a span the cut left open on the last line.
  let masked = cut.replace(/```[\s\S]*?```/g, blank).replace(/`[^`\n]*`/g, blank);
  const stray = masked.lastIndexOf("`");
  if (stray >= 0 && !masked.slice(stray).includes("\n")) {
    cut += "`";
    masked = masked.slice(0, stray) + "x".repeat(masked.length - stray + 1);
  }

  // A dangling marker run at the very end ("text **") has nothing to emphasise.
  const dangling = masked.match(/(?:^|\s)[*_]+$/);
  if (dangling) {
    cut = cut.slice(0, masked.length - dangling[0].trimStart().length).trimEnd();
    masked = masked.slice(0, cut.length);
  }
  const closers = openEmphasis(masked).reverse().join("");
  return `${cut}${closers} …*more*`;
}
