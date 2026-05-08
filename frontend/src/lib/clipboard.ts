function legacyCopy(text: string): void {
  const el = document.createElement("textarea");
  el.value = text;
  el.style.cssText = "position:fixed;opacity:0;pointer-events:none";
  document.body.appendChild(el);
  el.select();
  document.execCommand("copy");
  document.body.removeChild(el);
}

export async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
  } else {
    legacyCopy(text);
  }
}
