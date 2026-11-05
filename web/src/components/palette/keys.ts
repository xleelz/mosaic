/** True when focus is somewhere that owns its keys: a text field, a select, or the code viewer. */
export function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (el.isContentEditable || el.closest(".cm-editor, [data-code-viewer]")) return true;
  const tag = el.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag !== "INPUT") return false;
  const type = (el as HTMLInputElement).type;
  return type !== "checkbox" && type !== "radio" && type !== "button";
}
