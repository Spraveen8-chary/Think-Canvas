// Shrinks an imported picture before it is stored or sent to the AI (smaller picture = fewer tokens).
export async function shrinkImage(file, maxSide = 1024) {
  const bitmap = await createImageBitmap(file);
  const k = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * k)), h = Math.max(1, Math.round(bitmap.height * k));
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const g = c.getContext("2d");
  g.fillStyle = "#fff";                       // transparent PNGs get a white background
  g.fillRect(0, 0, w, h);
  g.drawImage(bitmap, 0, 0, w, h);
  const blob = await new Promise((resolve) => c.toBlob(resolve, "image/jpeg", 0.88));
  return { blob, w, h };
}
